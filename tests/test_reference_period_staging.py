"""Fetching and computation stage through one reference-period window.

The November 2026 attempt to prepare the October 2026 release failed
because ``scripts.test_bls_api`` chose its staging files from the date it
ran (November, so ``*_2026_2027.json``) while ``scripts.compute_dmi_release``
chose them from the reference period (``*_2025_2026.json``). Both now use
``scripts.reference_period``, and the fetch validates every required
observation before it writes.

Every BLS request here is mocked, and every write lands in a temporary
directory. No published data and no committed staging file is touched.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import yaml

from scripts import test_bls_api as fetch
from scripts.reference_period import (
    parse_reference_period,
    staging_paths,
    staging_window_for_period,
    year_over_year_base,
)

ROOT = Path(__file__).resolve().parents[1]
MONTHLY = ROOT / ".github" / "workflows" / "monthly_dmi.yml"
WORKFLOWS = ROOT / ".github" / "workflows"
CATALOG = json.loads((ROOT / "registry" / "series_catalog_v0_1.json").read_text())

CPI_SERIES = {
    cat["series_id"]: cat["category_id"]
    for cat in CATALOG["cpi"]["series_sets"][0]["categories"]
    if cat["category_id"] != "CPI_ALL_ITEMS"
}
U3_SERIES = next(s["series_id"] for s in CATALOG["slack"]["national_series"]
                 if s["metric"] == "U3")
U6_SERIES = next(s["series_id"] for s in CATALOG["slack"]["national_series"]
                 if s["metric"] == "U6")

#: Official observations BLS never published (2025 federal shutdown).
UNPUBLISHED = {"2025-10"}


def _months(start_year: int, end_year: int):
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            yield f"{year:04d}-{month:02d}"


def _cpi_level(period: str) -> float:
    """Synthetic CPI: each period one year after its base is 3% higher.

    Levels also vary within a year, so a wrong base month would yield a
    visibly different inflation rate.
    """
    year, month = parse_reference_period(period)
    return 100.0 * 1.03 ** (year - 2020) + month


class FakeBLS:
    """Stands in for the BLS API in ``scripts.test_bls_api``.

    Returns long-format frames shaped like ``fetch_cpi_data``. Data exist
    up to ``last_published``; ``UNPUBLISHED`` and anything in ``drop``
    (``(period, series_id)`` pairs, or periods for every series) are
    absent, as BLS omits them.
    """

    def __init__(self, last_published: str, drop=()):
        self.last_published = last_published
        self.drop = set(drop)
        self.calls: list[tuple[tuple[str, ...], int, int]] = []

    def _frame(self, series_ids, start_year, end_year, value):
        self.calls.append((tuple(series_ids), start_year, end_year))
        rows = []
        for sid in series_ids:
            for period in _months(start_year, end_year):
                if (period > self.last_published or period in UNPUBLISHED
                        or period in self.drop or (period, sid) in self.drop):
                    continue
                year, month = period.split("-")
                rows.append({"series_id": sid, "year": int(year),
                             "period": f"M{month}", "period_name": "",
                             "value": value(period), "footnotes": []})
        return pd.DataFrame(rows)

    def fetch_cpi_data(self, series_ids, start_year, end_year, api_key=None):
        return self._frame(series_ids, start_year, end_year, _cpi_level)

    def fetch_slack_data(self, series_id, start_year, end_year, api_key=None):
        return self._frame([series_id], start_year, end_year, lambda p: 4.2)

    @contextlib.contextmanager
    def installed(self):
        with patch.object(fetch, "fetch_cpi_data", self.fetch_cpi_data), \
             patch.object(fetch, "fetch_slack_data", self.fetch_slack_data):
            yield self


def _quiet():
    return contextlib.redirect_stdout(io.StringIO())


class _Staging:
    """A temporary staging directory, optionally seeded with a file."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "staging"
        self.dir.mkdir()
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()
        return False

    def snapshot(self) -> dict[str, bytes]:
        return {p.name: p.read_bytes() for p in sorted(self.dir.iterdir())}


# -- A. One source of truth for the staging window ---------------------------


class TestStagingWindow(unittest.TestCase):

    def test_convention(self):
        expected = {
            "2026-09": (2025, 2026),
            "2026-10": (2025, 2026),
            "2026-11": (2026, 2027),
            "2026-12": (2026, 2027),
            "2027-01": (2026, 2027),
        }
        for period, window in expected.items():
            with self.subTest(period=period):
                self.assertEqual(staging_window_for_period(period), window)

    def test_september_and_october_share_a_window(self):
        self.assertEqual(staging_paths("2026-09"), staging_paths("2026-10"))

    def test_october_to_november_transition(self):
        october, november = staging_paths("2026-10"), staging_paths("2026-11")
        self.assertEqual(october["cpi"].name, "cpi_levels_2025_2026.json")
        self.assertEqual(november["cpi"].name, "cpi_levels_2026_2027.json")
        self.assertEqual(november["u3"].name, "slack_u3_2026_2027.json")
        self.assertEqual(november["u6"].name, "slack_u6_2026_2027.json")

    def test_december_to_january_stays_in_one_window(self):
        self.assertEqual(staging_paths("2026-12"), staging_paths("2027-01"))
        self.assertEqual(staging_window_for_period("2027-10"), (2026, 2027))
        self.assertEqual(staging_window_for_period("2027-11"), (2027, 2028))

    def test_year_over_year_base(self):
        self.assertEqual(year_over_year_base("2026-11"), "2025-11")
        self.assertEqual(year_over_year_base("2026-10"), "2025-10")
        self.assertEqual(year_over_year_base("2027-01"), "2026-01")

    def test_invalid_reference_periods_are_rejected(self):
        for bad in ("2026-13", "2026-00", "2026-1", "26-10", "2026/10",
                    "2026-10-01", " 2026-10", "2026-10\n", "", "Oct 2026", None):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    staging_window_for_period(bad)
                with self.assertRaises(ValueError):
                    year_over_year_base(bad)

    def test_fetch_and_compute_import_the_same_function(self):
        from scripts import compute_dmi_release, reference_period
        self.assertIs(compute_dmi_release.staging_window_for_period,
                      reference_period.staging_window_for_period)
        self.assertIs(fetch.staging_window_for_period,
                      reference_period.staging_window_for_period)

    def test_compute_rejects_an_invalid_period(self):
        from scripts.compute_dmi_release import main as compute_release
        with patch.object(sys, "argv", ["compute_dmi_release", "2026-13"]), _quiet():
            with self.assertRaises(SystemExit) as raised:
                compute_release()
        self.assertIn("Invalid reference period", str(raised.exception))

    def test_window_never_comes_from_the_clock(self):
        """Neither module may consult the execution date."""
        for module in ("test_bls_api.py", "reference_period.py"):
            tree = ast.parse((ROOT / "scripts" / module).read_text())
            names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
            attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
            imported = {a.name.split(".")[0] for n in ast.walk(tree)
                        if isinstance(n, (ast.Import, ast.ImportFrom))
                        for a in n.names}
            imported |= {n.module for n in ast.walk(tree)
                         if isinstance(n, ast.ImportFrom) and n.module}
            with self.subTest(module=module):
                self.assertFalse({"datetime", "time", "date"} & imported)
                self.assertFalse({"now", "today", "utcnow"} & attrs)
                self.assertNotIn("datetime", names)


# -- B. The acquisition script ----------------------------------------------


class TestCommandLine(unittest.TestCase):

    def test_reference_period_is_required(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            fetch.parse_args([])
        self.assertEqual(raised.exception.code, 2)

    def test_invalid_reference_period_is_rejected(self):
        for bad in ("2026-13", "2026-1", "202610"):
            with self.subTest(value=bad):
                err = io.StringIO()
                with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as raised:
                    fetch.parse_args(["--reference-period", bad])
                self.assertEqual(raised.exception.code, 2)
                self.assertIn("Invalid reference period", err.getvalue())

    def test_valid_reference_period_is_accepted(self):
        self.assertEqual(fetch.parse_args(["--reference-period", "2026-11"]).reference_period,
                         "2026-11")


class TestAcquisition(unittest.TestCase):

    def _acquire(self, period, bls, staging):
        with bls.installed(), _quiet():
            return fetch.acquire(period, staging_dir=staging.dir,
                                 catalog_path=ROOT / "registry" / "series_catalog_v0_1.json")

    def _assert_fails_without_writing(self, period, bls, *fragments):
        with _Staging() as staging:
            seeded = staging_paths(period, staging.dir)["cpi"]
            seeded.write_text('{"data": [], "metadata": {"seeded": true}}')
            before = staging.snapshot()
            with self.assertRaises(fetch.AcquisitionError) as raised:
                self._acquire(period, bls, staging)
            self.assertEqual(staging.snapshot(), before,
                             "staging changed although validation failed")
        message = str(raised.exception)
        self.assertIn("nothing was staged", message)
        for fragment in fragments:
            self.assertIn(fragment, message)
        return message

    def test_november_2026_stages_the_2026_2027_window(self):
        bls = FakeBLS(last_published="2026-11")
        with _Staging() as staging:
            written = self._acquire("2026-11", bls, staging)
            self.assertEqual({p.name for p in written.values()},
                             {"cpi_levels_2026_2027.json", "slack_u3_2026_2027.json"})
            self.assertEqual(sorted(staging.snapshot()),
                             ["cpi_levels_2026_2027.json", "slack_u3_2026_2027.json"])
            cpi_periods = {r["period"] for r in
                           json.loads(written["cpi"].read_text())["data"]}
            u3_periods = {r["period"] for r in json.loads(written["u3"].read_text())}
        # The request spans the base month and the reference month.
        self.assertEqual({(start, end) for _, start, end in bls.calls}, {(2025, 2027)})
        self.assertTrue({"2025-11", "2026-11"} <= cpi_periods)
        self.assertIn("2026-11", u3_periods)
        # October 2025 is absent and does not block November 2026.
        self.assertNotIn("2025-10", cpi_periods)

    def test_historical_rerun_uses_its_own_window(self):
        """A rerun of 2025-12 today writes the 2025_2026 window, not 2026_2027."""
        bls = FakeBLS(last_published="2026-11")
        with _Staging() as staging:
            written = self._acquire("2025-12", bls, staging)
            self.assertEqual(written["cpi"].name, "cpi_levels_2025_2026.json")
            self.assertEqual(written["u3"].name, "slack_u3_2025_2026.json")
        self.assertEqual({(start, end) for _, start, end in bls.calls}, {(2024, 2026)})

    def test_missing_base_month_fails(self):
        bls = FakeBLS(last_published="2026-11", drop={"2025-11"})
        self._assert_fails_without_writing(
            "2026-11", bls, "2025-11 (12-month CPI base month)")

    def test_missing_reference_month_fails(self):
        bls = FakeBLS(last_published="2026-10")
        self._assert_fails_without_writing(
            "2026-11", bls, "2026-11 (reference month)", "U-3 has no observation for 2026-11")

    def test_missing_category_in_reference_month_fails(self):
        sid = next(iter(CPI_SERIES))
        bls = FakeBLS(last_published="2026-11", drop={("2026-11", sid)})
        self._assert_fails_without_writing(
            "2026-11", bls, f"{CPI_SERIES[sid]} (t=2026-11)")

    def test_missing_category_in_base_month_fails(self):
        sid = list(CPI_SERIES)[-1]
        bls = FakeBLS(last_published="2026-11", drop={("2025-11", sid)})
        self._assert_fails_without_writing(
            "2026-11", bls, f"{CPI_SERIES[sid]} (t-12=2025-11)")

    def test_missing_reference_month_u3_fails(self):
        bls = FakeBLS(last_published="2026-11", drop={("2026-11", U3_SERIES)})
        message = self._assert_fails_without_writing(
            "2026-11", bls, "U-3 has no observation for 2026-11")
        self.assertNotIn("CPI", message.split("nothing was staged")[1].split("U-3")[0])

    def test_october_2026_fails_on_unpublished_october_2025(self):
        bls = FakeBLS(last_published="2026-11")
        self._assert_fails_without_writing(
            "2026-10", bls, "CPI has no observations for 2025-10 (12-month CPI base month)",
            "not estimated")

    def test_main_reports_failure_and_exits_nonzero(self):
        """main() uses the repository-relative staging path, so run it from
        a scratch working directory holding only the series catalog."""
        bls = FakeBLS(last_published="2026-11")
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / "registry").mkdir()
            shutil.copy2(ROOT / "registry" / "series_catalog_v0_1.json", work / "registry")
            cwd = Path.cwd()
            os.chdir(work)
            try:
                with bls.installed(), _quiet(), contextlib.redirect_stderr(err):
                    self.assertEqual(fetch.main(["--reference-period", "2026-10"]), 1)
                self.assertFalse((work / "data").exists())
            finally:
                os.chdir(cwd)
        self.assertIn("2025-10 (12-month CPI base month)", err.getvalue())


# -- C. Workflow forwarding ---------------------------------------------------


def fetch_invocation_violations(doc: dict) -> list[str]:
    """Every fetch invocation that does not forward the resolved period."""
    found = []
    for job_id, job in (doc.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            run = str(step.get("run", ""))
            if "scripts.test_bls_api" not in run:
                continue
            joined = run.replace("\\\n", " ")
            for line in joined.splitlines():
                if "scripts.test_bls_api" not in line or line.strip().startswith("#"):
                    continue
                if '--reference-period "${{ steps.period.outputs.period }}"' not in line:
                    found.append(f"{job_id}/{step.get('name')}: {line.strip()}")
    return found


class TestWorkflowForwarding(unittest.TestCase):

    def setUp(self):
        self.doc = yaml.safe_load(MONTHLY.read_text())
        self.steps = self.doc["jobs"]["prepare-dmi"]["steps"]

    def _index(self, name):
        names = [s.get("name") for s in self.steps]
        self.assertIn(name, names)
        return names.index(name)

    def test_fetch_forwards_the_resolved_period(self):
        self.assertEqual(fetch_invocation_violations(self.doc), [])
        step = self.steps[self._index("Fetch CPI data (live only)")]
        self.assertEqual(step["if"], "steps.mode.outputs.data_source == 'live'")
        self.assertIn("BLS_API_KEY", step["env"])

    def test_period_is_resolved_before_fetch_and_fetch_precedes_compute(self):
        period = self._index("Resolve reference period")
        fetch_step = self._index("Fetch CPI data (live only)")
        baseline = self._index("Compute DMI Baseline (live only)")
        slack_plus = self._index("Compute DMI Slack+ (live only)")
        finalize = self._index("Finalize release (gates, then publish) — live only")
        self.assertLess(period, fetch_step)
        self.assertLess(fetch_step, baseline)
        self.assertLess(baseline, slack_plus)
        self.assertLess(slack_plus, finalize)

    def test_no_workflow_calls_the_fetch_without_a_period(self):
        invocations = 0
        for path in sorted(WORKFLOWS.glob("*.yml")):
            doc = yaml.safe_load(path.read_text())
            with self.subTest(workflow=path.name):
                self.assertEqual(fetch_invocation_violations(doc), [])
            invocations += path.read_text().count("python -m scripts.test_bls_api")
        self.assertEqual(invocations, 1, "expected exactly one fetch invocation")

    def test_checker_flags_a_fetch_without_the_period(self):
        """Non-vacuity: the old invocation must be caught."""
        doc = {"jobs": {"release": {"steps": [
            {"name": "Fetch", "run": 'echo "Fetching"\npython -m scripts.test_bls_api\n'},
            {"name": "Fetch2", "run": "python -m scripts.test_bls_api --reference-period 2026-10"},
        ]}}}
        self.assertEqual(len(fetch_invocation_violations(doc)), 2)


# -- D. The next normal release: 2026-11 end to end, offline -----------------


class TestNovember2026FeedsBothSpecifications(unittest.TestCase):
    """Mocked acquisition -> Baseline -> Slack-Plus -> finalization gates."""

    def test_end_to_end_in_a_scratch_tree(self):
        from scripts.compute_dmi_release import main as compute_release
        from scripts.finalize_release import finalize
        from tests.test_release_finalization import _RealTree

        period = "2026-11"
        bls = FakeBLS(last_published=period)
        with _RealTree() as tree:
            shutil.copytree(ROOT / "registry", tree.root / "registry")
            shutil.copytree(ROOT / "data" / "curated", tree.root / "data" / "curated")
            with bls.installed(), _quiet():
                written = fetch.acquire(period)
            self.assertEqual(
                {p.resolve() for p in written.values()},
                {(tree.root / "data/staging/cpi_levels_2026_2027.json").resolve(),
                 (tree.root / "data/staging/slack_u3_2026_2027.json").resolve()},
            )
            weights_year = json.loads(
                (tree.root / "data/curated/weights_by_group_latest.json").read_text()
            )["weights_year"]

            # Slack-Plus fetches U-6 itself, inside the compute step.
            from dmi_pipeline.agents import bls_api_client
            with patch.object(bls_api_client, "fetch_slack_data",
                              lambda sid, s, e, api_key=None:
                              bls._frame([sid], s, e, lambda p: 7.9)):
                for spec in ("baseline", "slack_plus"):
                    with patch.object(sys, "argv", [
                        "compute_dmi_release", period, "--spec", spec,
                        "--weights-year", str(weights_year),
                    ]), _quiet():
                        self.assertEqual(compute_release(), 0)
            self.assertIn(((U6_SERIES,), 2026, 2027), bls.calls)
            self.assertTrue((tree.root / "data/staging/slack_u6_2026_2027.json").is_file())

            baseline = json.loads((tree.outputs / f"dmi_release_{period}.json").read_text())
            slack_plus = json.loads(
                (tree.outputs / f"dmi_release_{period}_slack_plus.json").read_text())
            expected = 100 * (_cpi_level("2026-11") / _cpi_level("2025-11") - 1)
            for raw, slack in ((baseline, 4.2), (slack_plus, 7.9)):
                for group in raw["dmi_by_group"]:
                    # Inflation is measured against November 2025.
                    self.assertAlmostEqual(group["inflation"], expected, places=6)
                    self.assertAlmostEqual(group["slack"], slack)
            with _quiet():
                rc, problems, _ = finalize(period, output_dir=tree.outputs,
                                           repo_root=tree.root)
            self.assertEqual(rc, 0, problems)


if __name__ == "__main__":
    unittest.main()
