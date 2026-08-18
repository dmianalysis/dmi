#!/usr/bin/env python3
"""Behavioral coverage for transactional release finalization (Round-4 §1).

What these tests are for
------------------------
§1 requires that a release is published only after its QA outcome and
cross-specification identity have been checked, and that a failed gate
leaves every mutable public artifact byte-identical to its pre-run state.

Both halves need behavioral proof. A source-text grep can show that a
call to ``evaluate_qa_report`` exists; it cannot show that the call is
reached, that its result is acted on, or that nothing was written before
it ran. So every negative test here builds a real release tree, breaks
one specific thing, runs the real gate or the real finalizer, and
compares SHA-256 digests of the public surface before and after.

Isolation
---------
The publication writers address paths relative to the working directory
(``data/outputs/...``, ``web/health.json``), so a temporary tree plus a
``chdir`` gives complete isolation: no test in this file can modify the
repository's own published artifacts. ``_RealTree`` copies the genuine
2026-07 release — real numbers, real QA reports, real schemas — because
gates that only ever see synthetic input tend to encode the synthesis
rather than the requirement.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.finalize_release import (
    finalize,
    public_digest,
    run_gates,
)
from scripts.release_policy import check_cross_spec, evaluate_qa_report

REPO_ROOT = Path(__file__).resolve().parent.parent
PERIOD = "2026-07"


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


class _RealTree:
    """A throwaway copy of the real release, safe to corrupt.

    Copies the artifacts finalization reads and writes, plus the schemas
    the gates validate against, into a temporary directory. Everything
    the writers touch is relative to the working directory, so entering
    this context manager makes the repository unreachable.
    """

    KEEP_OUTPUTS = (
        f"dmi_release_{PERIOD}.json",
        f"dmi_release_{PERIOD}_slack_plus.json",
        f"qa_report_{PERIOD}_baseline.json",
        f"qa_report_{PERIOD}_slack_plus.json",
        f"dmi-{PERIOD}-baseline.csv",
        f"dmi-{PERIOD}-baseline.parquet",
        f"dmi-{PERIOD}-slack_plus.csv",
        f"dmi-{PERIOD}-slack_plus.parquet",
        "releases.json",
        "latest.json",
        "specifications.json",
    )

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.outputs = self.root / "data" / "outputs"
        self._cwd = None

        (self.outputs / "published").mkdir(parents=True)
        (self.outputs / "releases").mkdir(parents=True)
        (self.root / "web" / "dashboard").mkdir(parents=True)

        src = REPO_ROOT / "data" / "outputs"
        # Copy the whole outputs tree except the historical archive. The
        # manifests reference every past release, and step 7 builds
        # deployment staging, so a tree holding only the current period
        # would fail closure for reasons unrelated to what is under test.
        for item in sorted(src.iterdir()):
            if item.name in ("published", "releases"):
                continue
            if item.is_file():
                shutil.copy2(item, self.outputs / item.name)
        shutil.copy2(
            src / "published" / "dmi_timeseries.json",
            self.outputs / "published" / "dmi_timeseries.json",
        )
        for note in sorted((src / "releases").glob("*.html")):
            shutil.copy2(note, self.outputs / "releases" / note.name)
        shutil.copy2(
            REPO_ROOT / "web" / "health.json", self.root / "web" / "health.json"
        )
        shutil.copy2(
            REPO_ROOT / "web" / "dashboard.html",
            self.root / "web" / "dashboard.html",
        )
        shutil.copy2(
            REPO_ROOT / "web" / "dashboard" / ".htaccess",
            self.root / "web" / "dashboard" / ".htaccess",
        )
        shutil.copytree(REPO_ROOT / "schemas", self.root / "schemas")

    def __enter__(self):
        self._cwd = os.getcwd()
        os.chdir(self.root)
        return self

    def __exit__(self, *exc):
        os.chdir(self._cwd)
        self._tmp.cleanup()
        return False

    # -- mutation helpers ------------------------------------------------

    def raw(self, spec: str) -> Path:
        name = (f"dmi_release_{PERIOD}.json" if spec == "baseline"
                else f"dmi_release_{PERIOD}_slack_plus.json")
        return self.outputs / name

    def qa(self, spec: str) -> Path:
        return self.outputs / f"qa_report_{PERIOD}_{spec}.json"

    def edit_qa(self, spec: str, **changes):
        path = self.qa(spec)
        doc = json.loads(path.read_text())
        doc.update(changes)
        path.write_text(json.dumps(doc, indent=2))

    def edit_raw(self, spec: str, mutate):
        path = self.raw(spec)
        doc = json.loads(path.read_text())
        mutate(doc)
        path.write_text(json.dumps(doc, indent=2))
        # Keep the QA binding honest unless the test is about the binding.
        self.rebind(spec)

    def rebind(self, spec: str):
        """Re-point the QA subject hash at the current raw bytes."""
        qa_path = self.qa(spec)
        doc = json.loads(qa_path.read_text())
        if "subject" in doc:
            doc["subject"]["raw_sha256"] = hashlib.sha256(
                self.raw(spec).read_bytes()
            ).hexdigest()
            qa_path.write_text(json.dumps(doc, indent=2))

    def digest(self) -> dict:
        return public_digest(PERIOD, repo_root=self.root)


class TestHealthyReleasePassesEveryGate(unittest.TestCase):
    """The real 2026-07 release must pass, or the negatives prove nothing."""

    def test_all_gates_pass_on_the_real_release(self):
        with _RealTree() as tree:
            problems, _warnings = run_gates(PERIOD, tree.outputs)
            self.assertEqual(
                problems, [],
                f"the unmodified real release must pass every gate: {problems}",
            )

    def test_warnings_are_surfaced_not_swallowed(self):
        """§1: warnings must be surfaced prominently, but must not block."""
        with _RealTree() as tree:
            problems, warnings = run_gates(PERIOD, tree.outputs)
            self.assertEqual(problems, [])
            self.assertGreater(
                len(warnings), 0,
                "the real release carries weights-vintage warnings; if none "
                "surface, warning propagation is broken and the other "
                "assertions about warnings are vacuous.",
            )


class GateRejectionCase(unittest.TestCase):
    """Base: break one thing, assert rejection AND zero public mutation."""

    def assert_rejected(self, tree: _RealTree, expect_substring: str):
        before = tree.digest()
        rc, problems, _warnings = finalize(
            PERIOD, output_dir=tree.outputs, repo_root=tree.root
        )
        after = tree.digest()

        self.assertEqual(rc, 1, "finalization must fail")
        self.assertTrue(problems, "failure must report at least one problem")
        joined = " | ".join(problems)
        self.assertIn(
            expect_substring, joined,
            f"expected a problem mentioning {expect_substring!r}; got: {joined}",
        )
        self.assertEqual(
            before, after,
            "§1: a failed gate must leave every mutable public artifact "
            "byte-identical. Changed: "
            + str({k: (before[k], after[k])
                   for k in before if before[k] != after[k]}),
        )


class TestQaOutcomePolicy(GateRejectionCase):
    """§1: the QA gate must enforce OUTCOME, not merely JSON shape."""

    def test_status_fail_is_rejected(self):
        with _RealTree() as tree:
            tree.edit_qa("baseline", status="FAIL")
            self.assert_rejected(tree, "QA status is 'FAIL'")

    def test_nonzero_hard_failure_count_is_rejected(self):
        with _RealTree() as tree:
            doc = json.loads(tree.qa("baseline").read_text())
            doc["summary"]["hard_fail_count"] = 2
            tree.qa("baseline").write_text(json.dumps(doc, indent=2))
            self.assert_rejected(tree, "hard failure(s)")

    def test_nonzero_policy_failure_count_is_rejected(self):
        with _RealTree() as tree:
            doc = json.loads(tree.qa("slack_plus").read_text())
            doc["summary"]["policy_fail_count"] = 1
            tree.qa("slack_plus").write_text(json.dumps(doc, indent=2))
            self.assert_rejected(tree, "policy failure(s)")

    def test_pass_with_warning_is_rejected_when_failures_are_nonzero(self):
        """The status string alone must not be trusted."""
        with _RealTree() as tree:
            doc = json.loads(tree.qa("baseline").read_text())
            doc["status"] = "PASS_WITH_WARNING"
            doc["summary"]["hard_fail_count"] = 1
            tree.qa("baseline").write_text(json.dumps(doc, indent=2))
            self.assert_rejected(tree, "hard failure(s)")

    def test_explicit_fail_entry_is_rejected_even_if_counts_lie(self):
        """Counts and check entries must agree; either one failing blocks."""
        with _RealTree() as tree:
            doc = json.loads(tree.qa("baseline").read_text())
            doc["hard_checks"][0]["status"] = "FAIL"
            tree.qa("baseline").write_text(json.dumps(doc, indent=2))
            self.assert_rejected(tree, "reports FAIL")

    def test_missing_report_is_rejected(self):
        with _RealTree() as tree:
            tree.qa("slack_plus").unlink()
            self.assert_rejected(tree, "QA report is missing")

    def test_malformed_report_is_rejected(self):
        with _RealTree() as tree:
            tree.qa("baseline").write_text("{ this is not json")
            self.assert_rejected(tree, "malformed JSON")

    def test_wrong_reference_period_is_rejected(self):
        with _RealTree() as tree:
            tree.edit_qa("baseline", reference_period="2026-06")
            self.assert_rejected(tree, "declares reference_period")

    def test_report_specification_mismatch_is_rejected(self):
        """§1: bind the report to the specification, not the filename."""
        with _RealTree() as tree:
            doc = json.loads(tree.qa("slack_plus").read_text())
            doc["subject"]["specification"] = "baseline"
            tree.qa("slack_plus").write_text(json.dumps(doc, indent=2))
            self.assert_rejected(tree, "subject declares specification")

    def test_report_bound_to_different_bytes_is_rejected(self):
        """A report that describes an artifact that has since changed."""
        with _RealTree() as tree:
            doc = json.loads(tree.qa("baseline").read_text())
            doc["subject"]["raw_sha256"] = "0" * 64
            tree.qa("baseline").write_text(json.dumps(doc, indent=2))
            self.assert_rejected(tree, "different bytes")

    def test_unbound_report_is_rejected_for_a_current_release(self):
        """A filename alone is not evidence."""
        with _RealTree() as tree:
            doc = json.loads(tree.qa("baseline").read_text())
            doc.pop("subject")
            tree.qa("baseline").write_text(json.dumps(doc, indent=2))
            self.assert_rejected(tree, "no `subject` binding")

    def test_swapped_reports_are_rejected(self):
        """Copying the Baseline report over the Slack-Plus one must fail.

        This is the concrete attack the binding exists to stop: the file
        is named correctly and validates perfectly.
        """
        with _RealTree() as tree:
            shutil.copy2(tree.qa("baseline"), tree.qa("slack_plus"))
            self.assert_rejected(tree, "subject declares specification")


class TestRawArtifactGate(GateRejectionCase):
    """§1 gate 3: raw outputs must validate and identify themselves."""

    def test_missing_slack_plus_raw_output_is_rejected(self):
        with _RealTree() as tree:
            tree.raw("slack_plus").unlink()
            self.assert_rejected(tree, "does not exist")

    def test_cross_spec_gate_fails_closed_when_a_raw_output_is_missing(self):
        """§1 gate 6 must not pass by omission.

        The missing-artifact case above is caught by gate 3, so gate 6's
        own fail-closed branch never runs in that test — a mutation that
        turned the branch into a silent skip changed nothing. This pins
        it directly: with one raw output unavailable, `run_gates` must
        report the cross-specification check as FAILED, not absent.

        It matters because gate 6 is the only check that compares the two
        specifications. If gate 3 were ever loosened, a half-computed
        release would otherwise sail through the comparison by having
        nothing to compare.
        """
        with _RealTree() as tree:
            tree.raw("slack_plus").unlink()
            problems, _warnings = run_gates(PERIOD, tree.outputs)
            self.assertTrue(
                any("cross-spec" in p for p in problems),
                f"§1: the cross-specification gate must record a failure "
                f"when it cannot run. Problems were: {problems}",
            )
            self.assertTrue(
                any("cannot pass by omission" in p or "skipped because" in p
                    for p in problems),
                f"§1: the failure must say the gate could not run, not "
                f"stay silent. Problems were: {problems}",
            )

    def test_cross_spec_gate_fails_closed_when_a_raw_output_is_malformed(self):
        with _RealTree() as tree:
            tree.raw("baseline").write_text("{ broken")
            problems, _warnings = run_gates(PERIOD, tree.outputs)
            self.assertTrue(
                any("cross-spec" in p for p in problems), problems
            )

    def test_malformed_raw_output_is_rejected(self):
        with _RealTree() as tree:
            tree.raw("baseline").write_text("{ not json at all")
            self.assert_rejected(tree, "not valid JSON")

    def test_schema_invalid_raw_output_is_rejected(self):
        with _RealTree() as tree:
            tree.edit_raw("baseline", lambda d: d.pop("summary_metrics"))
            self.assert_rejected(tree, "dmi_output.schema.json")

    def test_wrong_period_raw_output_is_rejected(self):
        with _RealTree() as tree:
            tree.edit_raw(
                "slack_plus",
                lambda d: d.__setitem__("reference_period", "2026-05"),
            )
            self.assert_rejected(tree, "declares reference_period")

    def test_wrong_specification_raw_output_is_rejected(self):
        with _RealTree() as tree:
            tree.edit_raw(
                "slack_plus",
                lambda d: d.__setitem__("specification", "baseline"),
            )
            self.assert_rejected(tree, "declares specification")


class TestCrossSpecificationIdentityGate(GateRejectionCase):
    """§1 gate 6: the two specs may differ ONLY in labor slack."""

    def test_price_side_mismatch_is_rejected(self):
        with _RealTree() as tree:
            def bump(doc):
                doc["dmi_by_group"][2]["inflation"] += 0.5
            tree.edit_raw("slack_plus", bump)
            self.assert_rejected(tree, "inflation differs")

    def test_weights_vintage_mismatch_is_rejected(self):
        with _RealTree() as tree:
            tree.edit_raw(
                "slack_plus",
                lambda d: d["parameters"].__setitem__("weights_year", 2021),
            )
            self.assert_rejected(tree, "weights_year")

    def test_price_construction_mismatch_is_rejected(self):
        with _RealTree() as tree:
            tree.edit_raw(
                "slack_plus",
                lambda d: d["parameters"].__setitem__(
                    "inflation_measure", "CORE_CPI"),
            )
            self.assert_rejected(tree, "inflation_measure")

    def test_price_side_inputs_mismatch_is_rejected(self):
        with _RealTree() as tree:
            def drop(doc):
                doc["inflation_contributions"] = \
                    doc["inflation_contributions"][:-1]
            tree.edit_raw("slack_plus", drop)
            self.assert_rejected(tree, "inflation_contributions differ")

    def test_wrong_slack_measure_is_rejected(self):
        with _RealTree() as tree:
            tree.edit_raw(
                "slack_plus",
                lambda d: d["parameters"].__setitem__("slack_measure", "u3"),
            )
            self.assert_rejected(tree, "slack_measure")

    def test_unexplained_dmi_difference_is_rejected(self):
        """A DMI gap larger than the slack gap implies something else moved."""
        with _RealTree() as tree:
            def bump(doc):
                doc["dmi_by_group"][1]["dmi"] += 2.0
            tree.edit_raw("slack_plus", bump)
            self.assert_rejected(tree, "not explained by the slack difference")

    def test_reference_period_mismatch_is_rejected(self):
        base = json.loads(
            (REPO_ROOT / "data" / "outputs" / f"dmi_release_{PERIOD}.json").read_text()
        )
        other = copy.deepcopy(base)
        other["reference_period"] = "2026-06"
        other["specification"] = "slack_plus"
        problems = check_cross_spec(base, other)
        self.assertTrue(
            any("reference periods differ" in p for p in problems), problems
        )

    def test_gate_accepts_a_legitimate_slack_difference(self):
        """Non-vacuity: the gate must not reject the real, correct pair."""
        base = json.loads(
            (REPO_ROOT / "data" / "outputs" / f"dmi_release_{PERIOD}.json").read_text()
        )
        slack = json.loads(
            (REPO_ROOT / "data" / "outputs"
             / f"dmi_release_{PERIOD}_slack_plus.json").read_text()
        )
        self.assertEqual(check_cross_spec(base, slack), [])
        # And the difference really is nonzero, so the gate is being asked
        # a real question.
        self.assertNotEqual(
            base["dmi_by_group"][0]["slack"],
            slack["dmi_by_group"][0]["slack"],
        )


class TestSuccessfulFinalizationPublishes(unittest.TestCase):
    """The positive path: gates pass, everything is written, tree verifies."""

    def test_finalization_publishes_and_verifies(self):
        with _RealTree() as tree:
            rc, problems, _warnings = finalize(
                PERIOD, output_dir=tree.outputs, repo_root=tree.root
            )
            self.assertEqual(rc, 0, f"finalization failed: {problems}")

            for rel in (
                "data/outputs/releases.json",
                "data/outputs/latest.json",
                "data/outputs/specifications.json",
                "data/outputs/published/dmi_timeseries.json",
                f"data/outputs/releases/{PERIOD}.html",
                "web/health.json",
            ):
                with self.subTest(artifact=rel):
                    self.assertTrue(
                        (tree.root / rel).is_file(),
                        f"§1 step 7 must produce {rel}",
                    )

            self.assertTrue(
                (tree.root / "deploy" / "health.json").is_file(),
                "§1 step 7 must build deployment staging",
            )

    def test_dry_run_publishes_nothing(self):
        with _RealTree() as tree:
            before = tree.digest()
            rc, problems, _w = finalize(
                PERIOD, output_dir=tree.outputs, repo_root=tree.root,
                dry_run=True,
            )
            self.assertEqual(rc, 0, problems)
            self.assertEqual(
                before, tree.digest(),
                "a dry run must not modify any public artifact",
            )


class TestComputationDoesNotPublish(unittest.TestCase):
    """§1: computation must not mutate public artifacts as a side effect."""

    def test_compute_release_module_calls_no_publication_writer(self):
        """Asserted on the parsed call graph, not on a substring."""
        import ast
        src = (REPO_ROOT / "scripts" / "compute_dmi_release.py").read_text()
        tree = ast.parse(src)
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        forbidden = {
            "update_releases_json",
            "update_latest_json",
            "update_health_json",
            "update_timeseries_json",
            "export_csv_parquet",
        }
        offenders = sorted(called & forbidden)
        self.assertEqual(
            offenders, [],
            f"§1: computation must not publish. Called: {offenders}",
        )

    def test_compute_release_module_does_not_import_publication_writers(self):
        import ast
        src = (REPO_ROOT / "scripts" / "compute_dmi_release.py").read_text()
        imported = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.ImportFrom):
                imported |= {a.name for a in node.names}
        forbidden = {
            "update_releases_json", "update_latest_json",
            "update_health_json", "update_timeseries_json",
            "export_csv_parquet",
        }
        self.assertEqual(
            sorted(imported & forbidden), [],
            "§1: importing the publication writers here is what made it "
            "easy to call them mid-computation.",
        )

    def test_finalizer_is_the_only_module_that_publishes(self):
        """Exactly one active entry point orchestrates publication."""
        import ast
        publishers = []
        for path in sorted((REPO_ROOT / "scripts").glob("*.py")):
            if path.name in ("compute_dmi.py", "finalize_release.py"):
                continue  # definitions live in compute_dmi; finalizer is the orchestrator
            tree = ast.parse(path.read_text())
            called = {
                n.func.id for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            }
            if {"update_releases_json", "update_latest_json"} & called:
                publishers.append(path.name)
        self.assertEqual(
            publishers, [],
            f"§1: no module other than scripts/finalize_release.py may "
            f"call the manifest publication writers. Offenders: "
            f"{publishers}",
        )


if __name__ == "__main__":
    unittest.main()
