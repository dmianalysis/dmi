"""Missing-period gate and releases-schema 3.0.0 / 3.1.0 compatibility.

Finalization must refuse a release that follows an unpublished month
unless that month is a reviewed entry in registry/unavailable_periods.json
with a substantive reason, sources and the approving pull request.
Dry-run and live finalization run the same gate.

The releases schema accepts 3.0.0 (every committed manifest) and 3.1.0
(every manifest written from now on). Nonconsecutive comparisons exist
only in 3.1.0, where their fields are required and month-over-month
fields are forbidden.

BLS is mocked and every write lands in a scratch copy of the tree.
"""

from __future__ import annotations

import ast
import contextlib
import copy
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

from scripts.unavailable_periods import (
    REGISTRY_RELATIVE_PATH,
    check_registry,
    gap_problems,
    intervening_months,
    load_registry,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / REGISTRY_RELATIVE_PATH
SCHEMA = json.loads((ROOT / "schemas" / "releases.schema.json").read_text())
OUTPUTS = ROOT / "data" / "outputs"


class _Quiet(contextlib.ExitStack):
    def __enter__(self):
        super().__enter__()
        self.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.enter_context(contextlib.redirect_stderr(io.StringIO()))
        return self


def valid_entry(release_id="2026-10"):
    return copy.deepcopy(next(e for e in json.loads(REGISTRY.read_text())["periods"]
                              if e["release_id"] == "2026-10")) | {"release_id": release_id}


def registry_doc(*entries):
    return {"description": "test registry", "periods": list(entries)}


# -- The registry ------------------------------------------------------------


class TestRegistry(unittest.TestCase):

    def test_committed_registry_is_valid(self):
        entries, problems = load_registry(REGISTRY)
        self.assertEqual(problems, [])
        self.assertEqual(set(entries), {"2026-10"})

    def test_october_2026_provenance(self):
        entry = load_registry(REGISTRY)[0]["2026-10"]
        self.assertEqual(entry["reason"],
                         "the required official CPI comparison data are unavailable")
        urls = {s["url"] for s in entry["sources"]}
        self.assertEqual(urls, {
            "https://www.bls.gov/bls/news-release/cpi.htm",
            "https://www.bls.gov/cpi/additional-resources/"
            "2025-federal-government-shutdown-impact-cpi-faq.htm",
        })
        self.assertIn("lapse in federal government appropriations", entry["detail"])
        self.assertIn("not estimated, interpolated or backfilled", entry["detail"])
        self.assertEqual(entry["approved_in"], "dmianalysis/dmi#40")

    def test_no_october_2026_value_exists(self):
        self.assertFalse(list(OUTPUTS.glob("dmi_release_2026-10*")))
        self.assertFalse(list(OUTPUTS.glob("qa_report_2026-10*")))
        for name in ("releases.json", "latest.json"):
            ids = {r["release_id"] for r in json.loads((OUTPUTS / name).read_text())["releases"]}
            self.assertNotIn("2026-10", ids)

    def _problems(self, *entries):
        return check_registry(registry_doc(*entries))[1]

    def test_malformed_entries_are_rejected(self):
        cases = {
            "missing reason": lambda e: e.pop("reason"),
            "short reason": lambda e: e.update(reason="no data"),
            "placeholder reason": lambda e: e.update(
                reason="monthly job failed, TODO explain properly"),
            "short detail": lambda e: e.update(detail="BLS"),
            "no sources": lambda e: e.update(sources=[]),
            "source without url": lambda e: e.update(sources=[{"title": "BLS"}]),
            "http source": lambda e: e.update(
                sources=[{"title": "BLS", "url": "http://www.bls.gov/cpi/"}]),
            "untitled source": lambda e: e.update(
                sources=[{"title": " ", "url": "https://www.bls.gov/cpi/"}]),
            "no approval": lambda e: e.pop("approved_in"),
            "vague approval": lambda e: e.update(approved_in="approved"),
            "bad period": lambda e: e.update(release_id="2026-13"),
            "unknown field": lambda e: e.update(estimated_value=7.1),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                entry = valid_entry()
                mutate(entry)
                self.assertNotEqual(self._problems(entry), [])

    def test_duplicates_are_rejected(self):
        problems = self._problems(valid_entry(), valid_entry())
        self.assertEqual(len(problems), 1)
        self.assertIn("duplicate entry for 2026-10", problems[0])

    def test_structure_is_required(self):
        for doc in ([], {}, {"periods": {}}, {"periods": ["2026-10"]}):
            with self.subTest(doc=doc):
                self.assertNotEqual(check_registry(doc)[1], [])

    def test_unreadable_registry_fails_the_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unavailable_periods.json"
            path.write_text("{not json")
            problems = gap_problems("2026-11", {"2026-09"}, path)
        self.assertTrue(any("not readable JSON" in p for p in problems), problems)

    def test_nothing_writes_the_registry(self):
        """Entries are reviewed by hand; no code or workflow creates them."""
        writers = {"write_text", "write_bytes", "dump", "open", "mkdir", "touch"}
        tree = ast.parse((ROOT / "scripts" / "unavailable_periods.py").read_text())
        called = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
                  for n in ast.walk(tree) if isinstance(n, ast.Call)}
        self.assertFalse(called & writers, called & writers)
        referencing = {
            p.relative_to(ROOT).as_posix()
            for base in ("scripts", "dmi_pipeline", "dmi_calculator")
            for p in (ROOT / base).rglob("*.py")
            if "unavailable_periods" in p.read_text()
        }
        self.assertEqual(referencing, {"scripts/unavailable_periods.py",
                                       "scripts/compute_dmi.py",
                                       "scripts/finalize_release.py"})
        for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
            with self.subTest(workflow=workflow.name):
                self.assertNotIn("unavailable_periods", workflow.read_text())


# -- The gap rule ------------------------------------------------------------


class TestGapRule(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "unavailable_periods.json"

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, *entries):
        self.path.write_text(json.dumps(registry_doc(*entries)))

    def test_intervening_months(self):
        self.assertEqual(intervening_months("2026-09", "2026-11"), ["2026-10"])
        self.assertEqual(intervening_months("2026-11", "2027-02"), ["2026-12", "2027-01"])
        self.assertEqual(intervening_months("2026-12", "2027-01"), [])

    def test_consecutive_needs_no_registry(self):
        self.assertFalse(self.path.exists())
        self.assertEqual(gap_problems("2026-10", {"2026-08", "2026-09"}, self.path), [])
        self.assertEqual(gap_problems("2027-01", {"2026-12"}, self.path), [])

    def test_first_release_has_no_gap(self):
        self.assertEqual(gap_problems("2025-12", set(), self.path), [])

    def test_documented_gap_passes(self):
        self.write(valid_entry("2026-10"))
        self.assertEqual(gap_problems("2026-11", {"2026-08", "2026-09"}, self.path), [])

    def test_undocumented_gap_fails_and_names_every_month(self):
        problems = gap_problems("2026-11", {"2026-09"}, self.path)
        self.assertEqual(len(problems), 1)
        self.assertIn("2026-11 follows 2026-09", problems[0])
        self.assertIn(": 2026-10.", problems[0])
        self.assertIn("Do not add an entry only because a monthly run failed", problems[0])

    def test_unexplained_future_gap_fails(self):
        """2026-10 is documented; a later gap is not covered by it."""
        self.write(valid_entry("2026-10"))
        published = {"2026-09", "2026-11"}
        problems = gap_problems("2027-02", published, self.path)
        self.assertEqual(len(problems), 1)
        self.assertIn("2027-02 follows 2026-11", problems[0])
        self.assertIn("2026-12, 2027-01", problems[0])

    def test_partly_documented_gap_names_only_the_undocumented_month(self):
        self.write(valid_entry("2026-10"))
        problems = gap_problems("2026-12", {"2026-09"}, self.path)
        self.assertEqual(len(problems), 1)
        self.assertIn(": 2026-11.", problems[0])

    def test_entry_for_a_published_month_is_contradictory(self):
        self.write(valid_entry("2026-10"), valid_entry("2026-08"))
        problems = gap_problems("2026-11", {"2026-08", "2026-09"}, self.path)
        self.assertEqual(len(problems), 1)
        self.assertIn("2026-08 is listed", problems[0])
        self.assertIn("but it is published", problems[0])

    def test_entry_for_the_month_being_finalized_is_contradictory(self):
        self.write(valid_entry("2026-10"))
        problems = gap_problems("2026-10", {"2026-09"}, self.path)
        self.assertEqual(len(problems), 1)
        self.assertIn("2026-10 is listed", problems[0])
        self.assertIn("cannot be finalized", problems[0])

    def test_malformed_registry_fails_even_without_a_gap(self):
        bad = valid_entry("2026-10")
        bad["sources"] = []
        self.write(bad)
        self.assertNotEqual(gap_problems("2026-10", {"2026-09"}, self.path), [])


# -- Finalization end to end -------------------------------------------------


class _November2026Tree:
    """Scratch copy of the real tree with computed 2026-11 raw outputs."""

    def __enter__(self):
        from scripts import test_bls_api as fetch
        from scripts.compute_dmi_release import main as compute_release
        from tests.test_reference_period_staging import FakeBLS
        from tests.test_release_finalization import _RealTree
        from dmi_pipeline.agents import bls_api_client

        self._stack = contextlib.ExitStack()
        self.tree = self._stack.enter_context(_RealTree())
        root = self.tree.root
        shutil.copytree(ROOT / "registry", root / "registry")
        shutil.copytree(ROOT / "data" / "curated", root / "data" / "curated")
        bls = FakeBLS(last_published="2026-11")
        weights_year = json.loads(
            (root / "data/curated/weights_by_group_latest.json").read_text())["weights_year"]
        with bls.installed(), _Quiet(), patch.object(
                bls_api_client, "fetch_slack_data",
                lambda sid, s, e, api_key=None: bls._frame([sid], s, e, lambda p: 7.9)):
            fetch.acquire("2026-11")
            for spec in ("baseline", "slack_plus"):
                with patch.object(sys, "argv", ["compute_dmi_release", "2026-11",
                                                "--spec", spec,
                                                "--weights-year", str(weights_year)]):
                    assert compute_release() == 0
        self.registry = root / REGISTRY_RELATIVE_PATH
        return self

    def __exit__(self, *exc):
        return self._stack.__exit__(*exc)

    def finalize(self, dry_run=False):
        from scripts.finalize_release import finalize
        with _Quiet():
            return finalize("2026-11", output_dir=self.tree.outputs,
                            repo_root=self.tree.root, dry_run=dry_run)

    def public(self):
        from scripts.finalize_release import public_digest
        return public_digest("2026-11", self.tree.root)


class TestFinalizationGate(unittest.TestCase):

    def test_november_2026_finalizes_with_october_documented(self):
        with _November2026Tree() as t:
            before = json.loads((t.tree.outputs / "releases.json").read_text())
            self.assertEqual(before["schema_version"], "3.0.0")
            rc, problems, _ = t.finalize(dry_run=True)
            self.assertEqual((rc, problems), (0, []))
            rc, problems, _ = t.finalize()
            self.assertEqual((rc, problems), (0, []))

            validator = Draft202012Validator(SCHEMA)
            for name in ("releases.json", "latest.json"):
                doc = json.loads((t.tree.outputs / name).read_text())
                with self.subTest(manifest=name):
                    self.assertEqual(doc["schema_version"], "3.1.0")
                    validator.validate(doc)
                    entry = next(r for r in doc["releases"] if r["release_id"] == "2026-11")
                    facts = entry["summary_facts"]
                    self.assertEqual(facts["overall_direction"], "nonconsecutive")
                    self.assertEqual(facts["unavailable_release_ids"], ["2026-10"])
                    self.assertIn("because the required official CPI comparison data "
                                  "are unavailable", entry["summary"])

            # Historical entries are carried over unchanged.
            after = json.loads((t.tree.outputs / "releases.json").read_text())
            old = {r["release_id"]: r for r in before["releases"]}
            for entry in after["releases"]:
                if entry["release_id"] in old:
                    with self.subTest(release=entry["release_id"]):
                        prior = old[entry["release_id"]]
                        for key in ("metrics", "summary", "summary_facts", "spec_urls"):
                            self.assertEqual(entry[key], prior[key])

    def _assert_rejected(self, t, fragment):
        before = t.public()
        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run):
                rc, problems, _ = t.finalize(dry_run=dry_run)
                self.assertEqual(rc, 1)
                self.assertTrue(any(fragment in p for p in problems), problems)
                self.assertEqual(t.public(), before, "public tree changed")

    def test_rejected_when_the_registry_entry_is_absent(self):
        with _November2026Tree() as t:
            t.registry.unlink()
            self._assert_rejected(t, "no reviewed entry in registry/unavailable_periods.json: 2026-10")

    def test_rejected_when_the_registry_entry_is_invalid(self):
        with _November2026Tree() as t:
            doc = json.loads(t.registry.read_text())
            doc["periods"][0]["sources"] = []
            t.registry.write_text(json.dumps(doc))
            self._assert_rejected(t, "'sources' must list at least one source")

    def test_rejected_when_the_registry_contradicts_the_manifest(self):
        with _November2026Tree() as t:
            doc = json.loads(t.registry.read_text())
            doc["periods"].append(valid_entry("2026-09"))
            t.registry.write_text(json.dumps(doc))
            self._assert_rejected(t, "2026-09 is listed")

    def test_consecutive_release_needs_no_registry(self):
        from scripts.finalize_release import run_gates
        from tests.test_release_finalization import PERIOD, _RealTree
        with _RealTree() as tree, tempfile.TemporaryDirectory() as tmp:
            problems, _ = run_gates(PERIOD, tree.outputs,
                                    registry_path=Path(tmp) / "absent.json")
        self.assertEqual(problems, [])

    def test_gate_runs_before_publication(self):
        """A gap problem stops finalization before the snapshot/publish step."""
        with _November2026Tree() as t:
            t.registry.unlink()
            with patch("scripts.finalize_release.publish") as publish:
                rc, _, _ = t.finalize()
            self.assertEqual(rc, 1)
            publish.assert_not_called()


# -- Schema compatibility ----------------------------------------------------


def _gap_entry():
    from scripts.compute_dmi import build_release_summary
    base = json.loads((OUTPUTS / "releases.json").read_text())
    september = next(r for r in base["releases"] if r["release_id"] == "2026-09")
    facts, text = build_release_summary(
        {"release_id": "2026-11", "data_through_label": "November 2026",
         "metrics": september["metrics"]}, september)
    return base, dict(copy.deepcopy(september), release_id="2026-11",
                      data_through_label="November 2026", summary=text,
                      summary_facts=facts)


class TestSchemaVersions(unittest.TestCase):

    def setUp(self):
        self.validator = Draft202012Validator(SCHEMA)

    def test_schema_is_valid_draft_2020_12(self):
        Draft202012Validator.check_schema(SCHEMA)

    def test_committed_3_0_0_manifests_still_validate(self):
        for path in (OUTPUTS / "releases.json", OUTPUTS / "latest.json",
                     ROOT / "deploy/data/outputs/releases.json",
                     ROOT / "deploy/data/outputs/latest.json"):
            if not path.exists():
                continue
            doc = json.loads(path.read_text())
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertEqual(doc["schema_version"], "3.0.0")
                self.validator.validate(doc)

    def test_existing_entries_are_valid_under_3_1_0(self):
        doc = json.loads((OUTPUTS / "releases.json").read_text())
        doc["schema_version"] = "3.1.0"
        self.validator.validate(doc)

    def _with_gap(self, version, mutate=None):
        base, entry = _gap_entry()
        doc = copy.deepcopy(base)
        doc["schema_version"] = version
        if mutate:
            mutate(entry["summary_facts"])
        doc["releases"].insert(0, entry)
        return doc

    def test_nonconsecutive_entry_is_valid_only_in_3_1_0(self):
        self.validator.validate(self._with_gap("3.1.0"))
        self.assertFalse(self.validator.is_valid(self._with_gap("3.0.0")))

    def test_3_1_0_requires_every_nonconsecutive_field(self):
        required = ["comparison_release_id", "comparison_months_elapsed",
                    "unavailable_release_ids", "median_delta_since_comparison",
                    "stress_delta_since_comparison", "spread_delta_since_comparison",
                    "tilt_delta_since_comparison", "unemployment_delta_since_comparison"]
        for field in required:
            with self.subTest(missing=field):
                self.assertFalse(self.validator.is_valid(
                    self._with_gap("3.1.0", lambda f: f.pop(field))))

    def test_3_1_0_forbids_monthly_fields_in_nonconsecutive_facts(self):
        forbidden = {
            "median_delta_mom": 0.1, "stress_delta_mom": 0.1, "spread_delta_mom": 0.1,
            "tilt_delta_mom": 0.1, "unemployment_delta_mom": 0.1,
            "spread_direction": "spread_widened_slightly",
        }
        for field, value in forbidden.items():
            with self.subTest(field=field):
                self.assertFalse(self.validator.is_valid(
                    self._with_gap("3.1.0", lambda f: f.update({field: value}))))

    def test_3_1_0_rejects_a_threshold_class_with_comparison_fields(self):
        doc = self._with_gap("3.1.0", lambda f: f.update(overall_direction="rose_sharply"))
        self.assertFalse(self.validator.is_valid(doc))

    def test_3_1_0_rejects_invalid_comparison_values(self):
        for mutate in (lambda f: f.update(comparison_months_elapsed=1),
                       lambda f: f.update(unavailable_release_ids=[]),
                       lambda f: f.update(comparison_release_id="2026-13")):
            with self.subTest():
                self.assertFalse(self.validator.is_valid(self._with_gap("3.1.0", mutate)))

    def test_monthly_entry_may_not_carry_comparison_fields(self):
        doc = json.loads((OUTPUTS / "releases.json").read_text())
        for version in ("3.0.0", "3.1.0"):
            bad = copy.deepcopy(doc)
            bad["schema_version"] = version
            bad["releases"][0]["summary_facts"]["comparison_release_id"] = "2026-08"
            with self.subTest(version=version):
                self.assertFalse(self.validator.is_valid(bad))

    def test_unknown_versions_are_rejected(self):
        doc = json.loads((OUTPUTS / "releases.json").read_text())
        for version in ("2.0.0", "3.0.1", "3.2.0", "4.0.0", ""):
            bad = dict(doc, schema_version=version)
            with self.subTest(version=version):
                self.assertFalse(self.validator.is_valid(bad))


if __name__ == "__main__":
    unittest.main()
