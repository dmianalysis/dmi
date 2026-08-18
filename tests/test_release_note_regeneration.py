#!/usr/bin/env python3
"""Release-note regeneration follows the manifest, not the filesystem.

The rule
--------
The release entry in ``releases.json`` DEFINES which specifications were
published for a period. The raw artifacts are evidence that the claim is
true. Before this, the direction was reversed: the command globbed the
outputs directory and treated whatever it found as published, which left
two silent errors.

**Advertised but missing.** A release whose ``spec_urls`` claims
Slack-Plus, with no Slack-Plus artifact on disk, rendered a Baseline-only
note and returned success — concealing a real publication gap behind a
note that looked deliberate.

**Present but unadvertised.** A stray Slack-Plus artifact — from an
interrupted run, or a hand-copied file — was promoted into a historical
note, presenting as published a series the manifest never claimed.

Neither is visible from the rendered output, which is why both survived
until now: the note looks perfectly well-formed in each case. The tests
below therefore assert on what was rendered *and* on what the command
returned, and the rollback tests compare SHA-256 digests.
"""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.regenerate_release_notes import (
    RegenerationError,
    advertised_specs,
    main as regenerate_main,
    render_one,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_OUTPUTS = REPO_ROOT / "data" / "outputs"

#: The literal the generator renders for the Slack-Plus row. Asserting on
#: "Slack-Plus" would pass vacuously — the table says "Slack+" — so every
#: presence/absence check below uses this constant, and
#: `test_slack_plus_label_is_what_the_generator_emits` proves it is the
#: string that actually appears when Slack-Plus IS published.
SLACK_PLUS_LABEL = "Slack+"

BASELINE_ONLY = "2026-02"    # legacy period: Baseline only, unsuffixed exports
TWO_SPEC = "2026-07"         # current period: Baseline + Slack-Plus
EARLIER_TWO_SPEC = "2026-06"


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


class _Tree:
    """A throwaway outputs tree seeded from the real repository."""

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

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()
        return False

    # -- helpers ---------------------------------------------------------

    def note(self, period: str) -> Path:
        return self.outputs / "releases" / f"{period}.html"

    def raw(self, period: str, spec: str) -> Path:
        suffix = "_slack_plus" if spec == "slack_plus" else ""
        return self.outputs / f"dmi_release_{period}{suffix}.json"

    def release(self, period: str) -> dict:
        doc = json.loads((self.outputs / "releases.json").read_text())
        return next(r for r in doc["releases"] if r["release_id"] == period)

    def edit_manifest(self, period: str, mutate):
        for name in ("releases.json", "latest.json"):
            path = self.outputs / name
            doc = json.loads(path.read_text())
            for entry in doc.get("releases", []):
                if entry.get("release_id") == period:
                    mutate(entry)
            path.write_text(json.dumps(doc, indent=2))

    def edit_raw(self, period: str, spec: str, mutate):
        path = self.raw(period, spec)
        doc = json.loads(path.read_text())
        mutate(doc)
        path.write_text(json.dumps(doc, indent=2))

    def digests(self) -> dict:
        d = {
            str(p.relative_to(self.outputs)): _sha(p)
            for p in sorted((self.outputs / "releases").glob("*.html"))
        }
        for name in ("releases.json", "latest.json", "specifications.json"):
            d[name] = _sha(self.outputs / name)
        return d

    def run(self, *periods, dry_run=False) -> int:
        argv = ["--output-dir", str(self.outputs)]
        if periods:
            argv += ["--periods", *periods]
        if dry_run:
            argv.append("--dry-run")
        return regenerate_main(argv)


class TestManifestDefinesThePublishedSet(unittest.TestCase):
    """The advertised set comes from spec_urls, not from a glob."""

    def test_advertised_specs_reads_spec_urls(self):
        with _Tree() as tree:
            self.assertEqual(
                advertised_specs(tree.release(TWO_SPEC)),
                ["baseline", "slack_plus"],
            )
            self.assertEqual(
                advertised_specs(tree.release(BASELINE_ONLY)), ["baseline"]
            )

    def test_baseline_only_release_succeeds_and_renders_one_spec(self):
        with _Tree() as tree:
            self.assertEqual(tree.run(BASELINE_ONLY), 0)
            note = tree.note(BASELINE_ONLY).read_text()
            self.assertNotIn(SLACK_PLUS_LABEL, note)
            self.assertNotIn("Core", note)

    def test_slack_plus_label_is_what_the_generator_emits(self):
        """Guard the guard: pin the literal the negative tests rely on.

        The generator renders "Slack+", not "Slack-Plus". Every
        absence assertion in this file would pass for the wrong reason if
        it used the longer spelling, so the constant is proven here
        against a period that really does publish Slack-Plus.
        """
        with _Tree() as tree:
            _path, html, _warnings = render_one(
                tree.release(TWO_SPEC), tree.outputs
            )
            self.assertIn(
                SLACK_PLUS_LABEL, html,
                "SLACK_PLUS_LABEL no longer matches the generator's "
                "output; the absence assertions in this file would become "
                "vacuous.",
            )

    def test_two_spec_release_renders_both(self):
        with _Tree() as tree:
            self.assertEqual(tree.run(TWO_SPEC), 0)
            _path, html, _warnings = render_one(
                tree.release(TWO_SPEC), tree.outputs
            )
            self.assertIn(SLACK_PLUS_LABEL, html)


class TestAdvertisedButMissingFails(unittest.TestCase):
    """The central control: a claim without evidence is a failure."""

    def test_missing_advertised_slack_plus_fails(self):
        with _Tree() as tree:
            tree.raw(TWO_SPEC, "slack_plus").unlink()
            self.assertEqual(
                tree.run(TWO_SPEC), 1,
                "§1: a release advertising Slack-Plus with no Slack-Plus "
                "artifact must fail, not quietly render Baseline only.",
            )

    def test_missing_advertised_slack_plus_leaves_everything_unchanged(self):
        with _Tree() as tree:
            tree.raw(TWO_SPEC, "slack_plus").unlink()
            before = tree.digests()
            self.assertEqual(tree.run(TWO_SPEC), 1)
            self.assertEqual(
                before, tree.digests(),
                "§1: a failed run must leave every note and manifest "
                "byte-identical.",
            )

    def test_the_failure_names_the_missing_artifact(self):
        with _Tree() as tree:
            tree.raw(TWO_SPEC, "slack_plus").unlink()
            with self.assertRaises(RegenerationError) as ctx:
                render_one(tree.release(TWO_SPEC), tree.outputs)
            self.assertIn("does not exist", str(ctx.exception))

    def test_note_is_not_silently_downgraded_to_baseline_only(self):
        """The specific silent behavior being removed."""
        with _Tree() as tree:
            before = _sha(tree.note(TWO_SPEC))
            tree.raw(TWO_SPEC, "slack_plus").unlink()
            tree.run(TWO_SPEC)
            self.assertEqual(
                before, _sha(tree.note(TWO_SPEC)),
                "§1: the note must not be rewritten without Slack-Plus.",
            )


class TestUnadvertisedArtifactIsNotPublished(unittest.TestCase):
    """A file on disk is not a publication claim."""

    def test_unadvertised_slack_plus_is_not_added_to_the_note(self):
        with _Tree() as tree:
            # A stray artifact for a Baseline-only historical period.
            shutil.copy2(
                tree.raw(TWO_SPEC, "slack_plus"),
                tree.raw(BASELINE_ONLY, "slack_plus"),
            )
            tree.edit_raw(
                BASELINE_ONLY, "slack_plus",
                lambda d: d.__setitem__("reference_period", BASELINE_ONLY),
            )
            self.assertEqual(tree.run(BASELINE_ONLY), 0)
            note = tree.note(BASELINE_ONLY).read_text()
            self.assertNotIn(
                SLACK_PLUS_LABEL, note,
                "§1: an unadvertised artifact must never be presented as "
                "published.",
            )

    def test_unadvertised_artifact_produces_a_warning(self):
        with _Tree() as tree:
            shutil.copy2(
                tree.raw(TWO_SPEC, "slack_plus"),
                tree.raw(BASELINE_ONLY, "slack_plus"),
            )
            _path, _html, warnings = render_one(
                tree.release(BASELINE_ONLY), tree.outputs
            )
            self.assertTrue(
                any("NOT advertised" in w for w in warnings),
                f"§1: an orphan artifact must be surfaced: {warnings}",
            )

    def test_orphan_does_not_fail_the_run(self):
        """It is a warning, not an error: the manifest is still coherent."""
        with _Tree() as tree:
            shutil.copy2(
                tree.raw(TWO_SPEC, "slack_plus"),
                tree.raw(BASELINE_ONLY, "slack_plus"),
            )
            self.assertEqual(tree.run(BASELINE_ONLY), 0)


class TestAdvertisedArtifactMustValidate(unittest.TestCase):
    """Evidence means valid evidence, not merely a file that exists."""

    def test_malformed_advertised_artifact_fails(self):
        with _Tree() as tree:
            tree.raw(TWO_SPEC, "slack_plus").write_text("{ not json")
            self.assertEqual(tree.run(TWO_SPEC), 1)

    def test_schema_invalid_advertised_artifact_fails(self):
        with _Tree() as tree:
            tree.edit_raw(TWO_SPEC, "baseline",
                          lambda d: d.pop("summary_metrics"))
            self.assertEqual(tree.run(TWO_SPEC), 1)

    def test_wrong_period_advertised_artifact_fails(self):
        with _Tree() as tree:
            tree.edit_raw(
                TWO_SPEC, "slack_plus",
                lambda d: d.__setitem__("reference_period", "2020-01"),
            )
            self.assertEqual(tree.run(TWO_SPEC), 1)

    def test_wrong_specification_advertised_artifact_fails(self):
        with _Tree() as tree:
            tree.edit_raw(
                TWO_SPEC, "slack_plus",
                lambda d: d.__setitem__("specification", "baseline"),
            )
            self.assertEqual(tree.run(TWO_SPEC), 1)

    def test_each_validation_failure_leaves_the_note_unchanged(self):
        for label, mutate in (
            ("malformed", lambda t: t.raw(TWO_SPEC, "slack_plus").write_text("{")),
            ("wrong period", lambda t: t.edit_raw(
                TWO_SPEC, "slack_plus",
                lambda d: d.__setitem__("reference_period", "2020-01"))),
            ("wrong spec", lambda t: t.edit_raw(
                TWO_SPEC, "slack_plus",
                lambda d: d.__setitem__("specification", "baseline"))),
        ):
            with self.subTest(case=label):
                with _Tree() as tree:
                    mutate(tree)
                    before = tree.digests()
                    self.assertEqual(tree.run(TWO_SPEC), 1)
                    self.assertEqual(before, tree.digests())


class TestNonOperationalAdvertisedSpecIsRejected(unittest.TestCase):
    """Core in a manifest is a manifest defect, not something to skip."""

    def test_advertised_core_fails(self):
        with _Tree() as tree:
            tree.edit_manifest(
                TWO_SPEC,
                lambda e: e["spec_urls"].__setitem__(
                    "core", {"csv": "/data/outputs/dmi-2026-07-core.csv",
                             "parquet": "/data/outputs/dmi-2026-07-core.parquet"}),
            )
            self.assertEqual(tree.run(TWO_SPEC), 1)

    def test_advertised_unknown_spec_fails(self):
        with _Tree() as tree:
            tree.edit_manifest(
                TWO_SPEC,
                lambda e: e["spec_urls"].__setitem__("experimental", {}),
            )
            self.assertEqual(tree.run(TWO_SPEC), 1)

    def test_missing_baseline_advertisement_fails(self):
        with _Tree() as tree:
            tree.edit_manifest(
                TWO_SPEC, lambda e: e["spec_urls"].pop("baseline"),
            )
            self.assertEqual(tree.run(TWO_SPEC), 1)

    def test_empty_spec_urls_fails(self):
        with _Tree() as tree:
            tree.edit_manifest(TWO_SPEC, lambda e: e.__setitem__("spec_urls", {}))
            self.assertEqual(tree.run(TWO_SPEC), 1)


class TestMultiPeriodIsAllOrNothing(unittest.TestCase):
    """An invalid later period must not leave earlier notes rewritten."""

    def test_invalid_second_period_leaves_first_period_note_unchanged(self):
        with _Tree() as tree:
            before = _sha(tree.note(EARLIER_TWO_SPEC))
            # Break only the later period.
            tree.raw(TWO_SPEC, "slack_plus").unlink()
            rc = tree.run(EARLIER_TWO_SPEC, TWO_SPEC)
            self.assertEqual(rc, 1)
            self.assertEqual(
                before, _sha(tree.note(EARLIER_TWO_SPEC)),
                "§1: the valid earlier period must not be written when a "
                "later selected period is invalid.",
            )

    def test_invalid_period_leaves_the_whole_tree_unchanged(self):
        with _Tree() as tree:
            before = tree.digests()
            tree.raw(TWO_SPEC, "slack_plus").unlink()
            self.assertEqual(tree.run(EARLIER_TWO_SPEC, TWO_SPEC), 1)
            self.assertEqual(before, tree.digests())

    def test_all_valid_periods_are_written_together(self):
        with _Tree() as tree:
            rc = tree.run(EARLIER_TWO_SPEC, TWO_SPEC)
            self.assertEqual(rc, 0)
            for period in (EARLIER_TWO_SPEC, TWO_SPEC):
                self.assertTrue(tree.note(period).is_file())

    def test_failure_is_reported_for_every_bad_period_at_once(self):
        with _Tree() as tree:
            tree.raw(TWO_SPEC, "slack_plus").unlink()
            tree.raw(EARLIER_TWO_SPEC, "slack_plus").unlink()
            self.assertEqual(tree.run(EARLIER_TWO_SPEC, TWO_SPEC), 1)


class TestWritePhaseRollsBack(unittest.TestCase):
    """A failure partway through the write phase restores every note."""

    def test_failure_during_replace_restores_all_notes(self):
        from scripts import regenerate_release_notes as mod

        with _Tree() as tree:
            before = tree.digests()
            real_replace = Path.replace
            calls = {"n": 0}

            def flaky(self, target):
                calls["n"] += 1
                if calls["n"] == 2:
                    raise OSError("simulated failure during replace")
                return real_replace(self, target)

            Path.replace = flaky
            try:
                rc = tree.run(EARLIER_TWO_SPEC, TWO_SPEC)
            finally:
                Path.replace = real_replace

            self.assertEqual(rc, 1, "the run must report failure")
            self.assertEqual(
                before, tree.digests(),
                "§1: a failure during the write phase must restore every "
                "note to its exact pre-run bytes.",
            )
            self.assertGreaterEqual(
                calls["n"], 2, "the simulated failure must have been reached"
            )

    def test_a_new_note_created_before_the_failure_is_removed(self):
        from scripts import regenerate_release_notes as mod

        with _Tree() as tree:
            # Remove one note so the run would CREATE it.
            tree.note(EARLIER_TWO_SPEC).unlink()
            self.assertIsNone(_sha(tree.note(EARLIER_TWO_SPEC)))

            real_replace = Path.replace
            calls = {"n": 0}

            def flaky(self, target):
                calls["n"] += 1
                if calls["n"] == 2:
                    raise OSError("simulated failure during replace")
                return real_replace(self, target)

            Path.replace = flaky
            try:
                tree.run(EARLIER_TWO_SPEC, TWO_SPEC)
            finally:
                Path.replace = real_replace

            self.assertIsNone(
                _sha(tree.note(EARLIER_TWO_SPEC)),
                "§1: a note that did not exist before must be deleted on "
                "rollback, not left behind.",
            )

    def test_no_temporary_files_survive_a_failure(self):
        with _Tree() as tree:
            real_replace = Path.replace

            def always_fail(self, target):
                raise OSError("simulated failure")

            Path.replace = always_fail
            try:
                tree.run(EARLIER_TWO_SPEC, TWO_SPEC)
            finally:
                Path.replace = real_replace

            leftovers = [
                p.name for p in (tree.outputs / "releases").iterdir()
                if p.name.startswith(".") and ".regen-" in p.name
            ]
            self.assertEqual(leftovers, [], f"temp files leaked: {leftovers}")


class TestDryRunIsReadOnly(unittest.TestCase):
    def test_dry_run_changes_nothing(self):
        with _Tree() as tree:
            before = tree.digests()
            self.assertEqual(tree.run(dry_run=True), 0)
            self.assertEqual(before, tree.digests())

    def test_dry_run_still_validates(self):
        with _Tree() as tree:
            tree.raw(TWO_SPEC, "slack_plus").unlink()
            before = tree.digests()
            self.assertEqual(
                tree.run(TWO_SPEC, dry_run=True), 1,
                "a dry run must still report an invalid release.",
            )
            self.assertEqual(before, tree.digests())


class TestNoComputationOrSynthesis(unittest.TestCase):
    """§1: never call DMI computation; never synthesize a release."""

    MODULES = (
        REPO_ROOT / "scripts" / "regenerate_release_notes.py",
        REPO_ROOT / "scripts" / "backfill_release_notes.py",
    )
    FORBIDDEN = {
        "compute_dmi_for_period", "load_cpi_data", "load_slack_data",
        "load_weights", "staging_window_for_period",
    }

    def test_no_computation_is_imported(self):
        for path in self.MODULES:
            imported = set()
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ImportFrom):
                    imported |= {a.name for a in node.names}
            with self.subTest(module=path.name):
                self.assertEqual(sorted(imported & self.FORBIDDEN), [])

    def test_no_computation_is_called(self):
        for path in self.MODULES:
            called = {
                n.func.id for n in ast.walk(ast.parse(path.read_text()))
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            }
            with self.subTest(module=path.name):
                self.assertEqual(sorted(called & self.FORBIDDEN), [])

    def test_no_companion_artifact_is_ever_created(self):
        with _Tree() as tree:
            tree.raw(TWO_SPEC, "slack_plus").unlink()
            tree.run(TWO_SPEC)
            self.assertFalse(
                tree.raw(TWO_SPEC, "slack_plus").exists(),
                "§1: a missing artifact must never be synthesized.",
            )

    def test_validation_uses_the_single_authority(self):
        """§1 item 5: no second validation implementation."""
        src = (REPO_ROOT / "scripts" / "regenerate_release_notes.py").read_text()
        imported = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.ImportFrom) and node.module and \
                    "release_evidence" in node.module:
                imported |= {a.name for a in node.names}
        self.assertIn("verify_raw_artifact", imported)
        self.assertIn("OPERATIONAL_SPECS", imported)


class TestWrapperPropagatesFailure(unittest.TestCase):
    """§1: the compatibility wrapper must not swallow a failure."""

    def test_wrapper_returns_the_safe_commands_status(self):
        from scripts.backfill_release_notes import main as wrapper
        with _Tree() as tree:
            tree.raw(TWO_SPEC, "slack_plus").unlink()
            rc = wrapper(["--periods", TWO_SPEC,
                          "--output-dir", str(tree.outputs)])
            self.assertEqual(rc, 1)

    def test_wrapper_returns_zero_on_success(self):
        from scripts.backfill_release_notes import main as wrapper
        with _Tree() as tree:
            rc = wrapper(["--periods", BASELINE_ONLY,
                          "--output-dir", str(tree.outputs)])
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
