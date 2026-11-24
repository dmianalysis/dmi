"""The missing-release watchdog (scripts/monthly_release_watchdog.py).

Every test runs against ``FakeGitHub``, an in-memory stand-in for the
GitHub REST API. Nothing here touches the network or creates a real
Issue. Job and step records are built from the real step names in
``monthly_dmi.yml``, and job logs from the real fetch step's script and
the real ``scripts.test_bls_api`` output (run against a fake BLS), so a
renamed step or a reworded error breaks these tests rather than silently
changing the classification.
"""

from __future__ import annotations

import ast
import base64
import io
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import traceback
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is a repo dependency
    yaml = None

from scripts import monthly_release_watchdog as wd

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
WATCHDOG_WORKFLOW = WORKFLOWS / "monthly_release_watchdog.yml"
MODULE = ROOT / "scripts" / "monthly_release_watchdog.py"
REPO = "dmianalysis/dmi"
REAL_REGISTRY = json.loads((ROOT / "registry" / "unavailable_periods.json").read_text())


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def monthly_step_names() -> list[str]:
    doc = yaml.safe_load((WORKFLOWS / "monthly_dmi.yml").read_text())
    return [s["name"] for s in doc["jobs"]["prepare-dmi"]["steps"]]


LIVE_ONLY = {"Fetch CPI data (live only)", "Compute DMI Baseline (live only)",
             "Compute DMI Slack+ (live only)",
             "Finalize release (gates, then publish) — live only"}
FIXTURE_ONLY = {"Verify release gates against committed artifacts — fixture only"}
PREPARE_ONLY = {"Ensure workflow files are not included in release PR",
                "Create Release PR (no deployment)"}


def job_record(failed_step=None, data_source="live"):
    """A jobs-API record for monthly_dmi.yml, failing at ``failed_step``."""
    steps, state = [{"name": "Set up job", "conclusion": "success"}], "success"
    for name in monthly_step_names():
        if state != "success":
            conclusion = "skipped"
        elif data_source == "fixture" and (name in LIVE_ONLY or name in PREPARE_ONLY):
            conclusion = "skipped"
        elif data_source == "live" and name in FIXTURE_ONLY:
            conclusion = "skipped"
        elif name == failed_step:
            conclusion = state = "failure"
        else:
            conclusion = "success"
        steps.append({"name": name, "conclusion": conclusion})
    if failed_step is not None:
        assert state == "failure", f"unknown step {failed_step!r}"
    return {"name": "prepare-dmi", "conclusion": state, "steps": steps}


# -- Job logs -----------------------------------------------------------------

def fetch_output(period, failure=None):
    """(stdout, stderr) of the real ``scripts.test_bls_api`` for ``period``.

    ``failure`` makes the BLS fetch raise instead, as the real client does
    for an HTTP, authentication or network error; the traceback is what
    the interpreter would print to stderr.
    """
    from scripts import test_bls_api as fetch
    from tests.test_reference_period_staging import FakeBLS
    out, err = io.StringIO(), io.StringIO()
    bls = FakeBLS(last_published="2026-11" if period <= "2026-11" else period,
                  drop=failure if isinstance(failure, set) else ())
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "registry").mkdir()
        shutil.copy2(ROOT / "registry" / "series_catalog_v0_1.json", work / "registry")
        cwd = Path.cwd()
        os.chdir(work)
        try:
            with bls.installed(), redirect_stdout(out), redirect_stderr(err):
                if isinstance(failure, BaseException):
                    def raising(*args, **kwargs):
                        raise failure
                    with patch.object(fetch, "fetch_cpi_data", raising):
                        try:
                            code = fetch.main(["--reference-period", period])
                        except BaseException as exc:  # what the interpreter prints
                            err.write("".join(traceback.format_exception(
                                type(exc), exc, exc.__traceback__)))
                            code = 1
                else:
                    code = fetch.main(["--reference-period", period])
        finally:
            os.chdir(cwd)
    return out.getvalue(), err.getvalue(), code


def actions_log(period, stdout, stderr, code, stderr_first=True):
    """A job log in GitHub's format around the real fetch step.

    Python buffers stdout but not stderr when it is not a terminal, so in a
    real log stderr usually comes first. Both orders are produced.
    """
    doc = yaml.safe_load((WORKFLOWS / "monthly_dmi.yml").read_text())
    step = next(s for s in doc["jobs"]["prepare-dmi"]["steps"] if s["name"] == wd.FETCH_STEP)
    script = step["run"].replace("${{ steps.period.outputs.period }}", period).splitlines()
    lines = ["##[group]Run actions/checkout@v6", "with:", "##[endgroup]",
             "Syncing repository: dmianalysis/dmi",
             "##[group]Run " + script[0]]
    lines += [f"\x1b[36;1m{line}\x1b[0m" for line in script]
    lines += ["shell: /usr/bin/bash -e {0}", "env:", "  BLS_API_KEY: ***", "##[endgroup]"]
    streams = [stderr.splitlines(), stdout.splitlines()]
    for stream in (streams if stderr_first else streams[::-1]):
        lines += stream
    if code:
        lines.append(f"##[error]Process completed with exit code {code}.")
    lines.append("Post job cleanup.")
    return "\n".join(f"2026-11-15T10:21:03.{i:07d}Z {line}" for i, line in enumerate(lines))


def october_log(**kwargs):
    """The log the approved October 2026 exception predicts."""
    return actions_log("2026-10", *fetch_output("2026-10"), **kwargs)


class FakeGitHub:
    """Serves the endpoints the watchdog reads, and records every request."""

    def __init__(self):
        self.runs, self.jobs, self.pulls = [], {}, []
        self.logs, self.log_status, self.downloads = {}, {}, []
        self.download_error = None
        self.issues, self.comments = [], {}
        self.manifest_ids = ["2026-09", "2026-08"]
        self.registry = REAL_REGISTRY
        self.requests = []
        self.fail = {}  # path prefix -> (status, message)

    # -- builders --------------------------------------------------------
    def run(self, run_id, created, event="schedule", conclusion="success",
            failed_step=None, data_source="live", status="completed", branch="main"):
        self.runs.append({"id": run_id, "event": event, "status": status,
                          "conclusion": conclusion if status == "completed" else None,
                          "created_at": created, "head_branch": branch,
                          "html_url": f"https://github.com/{REPO}/actions/runs/{run_id}"})
        self.jobs[run_id] = [{**job_record(failed_step, data_source), "id": run_id * 10}]

    def pr(self, number, period, created, merged_at=None, state="open", closed_at=None,
           title=None, labels=("automated", "release", "not-deployed"), branch=None):
        self.pulls.append({
            "number": number, "state": state, "created_at": created,
            "merged_at": merged_at, "closed_at": closed_at or merged_at,
            "title": title or f"DMI Release: {period} (not deployed)",
            "head": {"ref": branch or f"release/{period}-20261215103000"},
            "base": {"ref": "main"}, "labels": [{"name": n} for n in labels],
            "html_url": f"https://github.com/{REPO}/pull/{number}"})

    def issue(self, number, period, state="open", fingerprint=None):
        body = wd.issue_marker(period) + "\nreported earlier"
        if fingerprint:
            body += "\n" + wd.state_marker(fingerprint)
        self.issues.append({"number": number, "state": state, "body": body,
                            "title": wd.issue_title(period)})
        self.comments[number] = []

    # -- transport -------------------------------------------------------
    def __call__(self, method, path, body):
        self.requests.append((method, path, body))
        url = urlsplit(path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        route = url.path.removeprefix(f"/repos/{REPO}")
        for prefix, failure in self.fail.items():
            if route.startswith(prefix):
                return failure[0], {"message": failure[1]}
        if method == "POST":
            return self._post(route, body)
        if method != "GET":
            return 405, {"message": "fake supports GET and POST only"}
        if query.get("page", "1") != "1":
            return 200, {"workflow_runs": []} if route.endswith("/runs") else []
        if route == "/actions/workflows/monthly_dmi.yml":
            return 200, {"id": 7, "path": ".github/workflows/monthly_dmi.yml",
                         "html_url": f"https://github.com/{REPO}/actions/workflows/monthly_dmi.yml"}
        if route == "/actions/workflows/7/runs":
            since = query["created"].removeprefix(">=")
            return 200, {"workflow_runs": [r for r in self.runs if r["created_at"] >= since]}
        m = re.fullmatch(r"/actions/runs/(\d+)/jobs", route)
        if m:
            return 200, {"jobs": self.jobs[int(m.group(1))]}
        m = re.fullmatch(r"/actions/jobs/(\d+)/logs", route)
        if m:
            job_id = int(m.group(1))
            if job_id in self.log_status:
                return self.log_status[job_id], {"message": "log unavailable"}
            if job_id in self.logs:
                return 302, {"location": f"https://results.example/{job_id}?sig=s"}
            return 404, {"message": "Not Found"}
        if route == "/pulls":
            return 200, sorted(self.pulls, key=lambda p: p["created_at"], reverse=True)
        if route == "/contents/data/outputs/releases.json":
            return 200, self._file({"releases": [{"release_id": r} for r in self.manifest_ids]})
        if route == "/contents/registry/unavailable_periods.json":
            if self.registry is None:
                return 404, {"message": "Not Found"}
            return 200, self._file(self.registry)
        if route == "/issues":
            wanted = query.get("state", "open")
            return 200, [i for i in reversed(self.issues) if wanted in ("all", i["state"])]
        m = re.fullmatch(r"/issues/(\d+)/comments", route)
        if m:
            return 200, self.comments[int(m.group(1))]
        return 404, {"message": f"fake has no route {route}"}

    def download(self, url):
        """The signed-URL fetch. It receives only the URL, never the token."""
        self.downloads.append(url)
        if self.download_error:
            raise wd.WatchdogError(self.download_error)
        return self.logs[int(urlsplit(url).path.strip("/"))]

    @property
    def log_requests(self):
        return [p for _, p, _ in self.requests if p.endswith("/logs")]

    @staticmethod
    def _file(doc):
        return {"encoding": "base64", "content": base64.b64encode(json.dumps(doc).encode()).decode()}

    def _post(self, route, body):
        if route == "/issues":
            number = 900 + len(self.issues)
            self.issues.append({"number": number, "state": "open", **body})
            self.comments[number] = []
            return 201, {"number": number}
        m = re.fullmatch(r"/issues/(\d+)/comments", route)
        if m:
            self.comments[int(m.group(1))].append(body)
            return 201, {"id": 1}
        return 404, {"message": f"fake has no POST route {route}"}

    @property
    def writes(self):
        return [(m, p) for m, p, _ in self.requests if m != "GET"]


DEC = "2026-12-17T16:37:00Z"  # first December check; expects 2026-11
NOV = "2026-11-17T16:37:00Z"  # first November check; expects 2026-10


def check(fake, as_of=DEC):
    gh = wd.GitHubClient(REPO, fake, download=fake.download)
    ev = wd.gather(gh, utc(as_of))
    return ev, wd.classify(ev)


def run_main(fake, *argv, as_of=DEC):
    out, err = io.StringIO(), io.StringIO()
    with tempfile.TemporaryDirectory() as tmp:
        summary = Path(tmp) / "summary.md"
        old = os.environ.get("GITHUB_STEP_SUMMARY")
        os.environ["GITHUB_STEP_SUMMARY"] = str(summary)
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = wd.main(["--repo", REPO, *argv], transport=fake,
                               now=lambda: utc(as_of),
                               download=getattr(fake, "download", None))
        finally:
            if old is None:
                os.environ.pop("GITHUB_STEP_SUMMARY")
            else:
                os.environ["GITHUB_STEP_SUMMARY"] = old
        text = summary.read_text() if summary.exists() else ""
    return code, out.getvalue(), err.getvalue(), text


def healthy_december(fake):
    """The ordinary December cycle: scheduled run succeeded, PR opened."""
    fake.run(501, "2026-12-15T10:20:00Z")
    fake.pr(61, "2026-11", "2026-12-15T10:40:00Z")


# ---------------------------------------------------------------------------


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestClassification(unittest.TestCase):

    def test_01_november_scheduled_run_absent_after_grace(self):
        ev, v = check(FakeGitHub(), NOV)
        self.assertEqual(ev.period, "2026-10")
        self.assertEqual(v.classification, wd.SCHEDULED_RUN_MISSING)
        self.assertTrue(v.alert)
        # October's approved data gap does not excuse a missing trigger.
        self.assertTrue(ev.approved_unavailable)
        self.assertIn("not a missing schedule trigger", v.reason)

    def test_not_yet_due_inside_the_grace_period(self):
        ev, v = check(FakeGitHub(), "2026-12-17T10:00:00Z")
        self.assertEqual(v.classification, wd.NOT_YET_DUE)
        self.assertFalse(v.alert)

    def test_02_python_setup_failure_before_release_preparation(self):
        fake = FakeGitHub()
        fake.run(502, "2026-12-15T17:14:00Z", conclusion="failure", failed_step="Set up Python")
        ev, v = check(fake)
        self.assertEqual(v.classification, wd.SCHEDULED_RUN_FAILED)
        self.assertEqual((v.run.id, v.run.failed_job, v.run.failed_step),
                         (502, "prepare-dmi", "Set up Python"))
        self.assertIn("no approved exception", v.reason)
        self.assertEqual(fake.log_requests, [], "a setup failure needs no log")
        body = wd.render(ev, v)
        for needed in ("2026-11", "SCHEDULED_RUN_FAILED", "Set up Python",
                       "https://github.com/dmianalysis/dmi/actions/runs/502",
                       "Suggested action", "2026-12-17 16:37 UTC"):
            self.assertIn(needed, body)

    def test_03_successful_run_that_produced_no_pr(self):
        fake = FakeGitHub()
        fake.run(503, "2026-12-15T10:20:00Z")
        _, v = check(fake)
        self.assertEqual(v.classification, wd.RUN_SUCCEEDED_NO_RELEASE_PR)
        self.assertTrue(v.alert)

    def test_03b_closed_unmerged_pr_is_not_a_release(self):
        fake = FakeGitHub()
        fake.run(503, "2026-12-15T10:20:00Z")
        fake.pr(62, "2026-11", "2026-12-15T10:40:00Z", state="closed",
                closed_at="2026-12-16T09:00:00Z")
        _, v = check(fake)
        self.assertEqual(v.classification, wd.RUN_SUCCEEDED_NO_RELEASE_PR)
        self.assertIn("#62", " ".join(v.notes))

    def test_03c_pr_must_match_title_branch_and_labels(self):
        for kwargs in ({"labels": ("release",)}, {"branch": "fix/2026-11"},
                       {"title": "DMI Release: 2026-11"}):
            with self.subTest(**kwargs):
                fake = FakeGitHub()
                fake.run(503, "2026-12-15T10:20:00Z")
                fake.pr(63, "2026-11", "2026-12-15T10:40:00Z", **kwargs)
                self.assertEqual(check(fake)[1].classification,
                                 wd.RUN_SUCCEEDED_NO_RELEASE_PR)

    def test_04_open_release_pr_awaiting_review(self):
        fake = FakeGitHub()
        healthy_december(fake)
        _, v = check(fake)
        self.assertEqual(v.classification, wd.RELEASE_PR_PENDING_REVIEW)
        self.assertFalse(v.alert)
        self.assertEqual(v.pr.url, "https://github.com/dmianalysis/dmi/pull/61")
        code, out, _, _ = run_main(fake, "--notify")
        self.assertEqual(code, 0)
        self.assertEqual(fake.writes, [], "an open release PR must not open an Issue")

    def test_05_pr_merged_but_manifest_not_updated(self):
        fake = FakeGitHub()
        fake.run(505, "2026-12-15T10:20:00Z")
        fake.pr(65, "2026-11", "2026-12-15T10:40:00Z", state="closed",
                merged_at="2026-12-16T12:00:00Z")
        _, v = check(fake)
        self.assertEqual(v.classification, wd.MERGED_BUT_NOT_IN_MANIFEST)
        self.assertTrue(v.alert)

    def test_06_valid_merged_release_recorded_in_main(self):
        fake = FakeGitHub()
        fake.run(506, "2026-12-15T10:20:00Z")
        fake.pr(66, "2026-11", "2026-12-15T10:40:00Z", state="closed",
                merged_at="2026-12-16T12:00:00Z")
        fake.manifest_ids.insert(0, "2026-11")
        ev, v = check(fake)
        self.assertEqual(v.classification, wd.RELEASE_MERGED)
        self.assertFalse(v.alert)
        self.assertIn("does not deploy", v.reason)
        self.assertNotIn("deployed to", wd.render(ev, v))

    def test_06b_replayed_date_sees_the_pr_as_it_was(self):
        fake = FakeGitHub()
        fake.run(506, "2026-12-15T10:20:00Z")
        fake.pr(66, "2026-11", "2026-12-15T10:40:00Z", state="closed",
                merged_at="2026-12-20T12:00:00Z")
        self.assertEqual(check(fake, DEC)[1].classification, wd.RELEASE_PR_PENDING_REVIEW)

    def test_07_manual_recovery_after_a_scheduled_failure(self):
        fake = FakeGitHub()
        fake.run(507, "2026-12-15T17:14:00Z", conclusion="failure", failed_step="Set up Python")
        fake.run(508, "2026-12-16T09:00:00Z", event="workflow_dispatch")
        fake.pr(67, "2026-11", "2026-12-16T09:30:00Z")
        ev, v = check(fake)
        self.assertEqual(v.classification, wd.RELEASE_PR_PENDING_REVIEW)
        self.assertIn("recovered by PR #67", " ".join(v.notes))
        self.assertEqual(ev.manual_runs[0].data_source, "live")
        self.assertTrue(ev.manual_runs[0].opened_pr)

    def test_07b_manual_recovery_without_any_scheduled_trigger_still_warns(self):
        fake = FakeGitHub()
        fake.run(508, "2026-12-16T09:00:00Z", event="workflow_dispatch")
        fake.pr(67, "2026-11", "2026-12-16T09:30:00Z")
        _, v = check(fake)
        self.assertEqual(v.classification, wd.SCHEDULED_TRIGGER_MISSING)
        self.assertTrue(v.alert)
        self.assertIn(wd.RELEASE_PR_PENDING_REVIEW, v.reason)

    def test_08_manual_fixture_validation_is_not_release_preparation(self):
        fake = FakeGitHub()
        fake.run(509, "2026-12-15T17:14:00Z", conclusion="failure", failed_step="Set up Python")
        fake.run(510, "2026-12-16T09:00:00Z", event="workflow_dispatch", data_source="fixture")
        ev, v = check(fake)
        self.assertEqual(v.classification, wd.SCHEDULED_RUN_FAILED)
        self.assertEqual(ev.manual_runs[0].data_source, "fixture")
        self.assertIn("validate/fixture (not release preparation)", ev.manual_runs[0].describe())

    def test_08b_fixture_runs_do_not_stand_in_for_a_scheduled_run(self):
        fake = FakeGitHub()
        fake.run(510, "2026-12-15T11:00:00Z", event="workflow_dispatch", data_source="fixture")
        self.assertEqual(check(fake)[1].classification, wd.SCHEDULED_RUN_MISSING)

    def test_09_october_2026_registered_as_unavailable(self):
        fake = FakeGitHub()
        fake.run(511, "2026-11-15T10:20:00Z", conclusion="failure",
                 failed_step=wd.FETCH_STEP)
        fake.logs[5110] = october_log()
        ev, v = check(fake, NOV)
        self.assertEqual(ev.period, "2026-10")
        self.assertTrue(ev.approved_unavailable)
        self.assertEqual(v.classification, wd.APPROVED_SOURCE_UNAVAILABLE)
        self.assertFalse(v.alert)
        self.assertIn("dmianalysis/dmi#40", v.reason)
        self.assertIn("CPI comparison data are unavailable", v.reason)
        self.assertIn("only because CPI has no observations for 2025-10", v.reason)

    def test_10_approved_gap_does_not_conceal_an_infrastructure_failure(self):
        # This is what actually happened on November 15, 2026.
        for step in ("Set up Python", "Install dependencies", "Resolve reference period"):
            with self.subTest(step=step):
                fake = FakeGitHub()
                fake.run(512, "2026-11-15T17:14:00Z", conclusion="failure", failed_step=step)
                ev, v = check(fake, NOV)
                self.assertTrue(ev.approved_unavailable)
                self.assertEqual(v.classification, wd.SCHEDULED_RUN_FAILED)
                self.assertIn("does not explain this failure", v.reason)

    def test_10b_failure_after_the_fetch_is_not_explained_either(self):
        fake = FakeGitHub()
        fake.run(513, "2026-11-15T10:20:00Z", conclusion="failure",
                 failed_step="Compute DMI Baseline (live only)")
        self.assertEqual(check(fake, NOV)[1].classification, wd.SCHEDULED_RUN_FAILED)

    def test_10c_cancelled_run_is_not_explained(self):
        fake = FakeGitHub()
        fake.run(514, "2026-11-15T10:20:00Z", conclusion="cancelled")
        self.assertEqual(check(fake, NOV)[1].classification, wd.SCHEDULED_RUN_FAILED)

    def test_11_failed_cpi_acquisition_with_an_approved_exception(self):
        for stderr_first in (True, False):
            with self.subTest(stderr_first=stderr_first):
                fake = FakeGitHub()
                fake.run(515, "2026-11-15T10:20:00Z", conclusion="failure",
                         failed_step=wd.FETCH_STEP)
                fake.logs[5150] = october_log(stderr_first=stderr_first)
                ev, v = check(fake, NOV)
                self.assertTrue(v.run.steps_before_failure_succeeded)
                self.assertEqual(v.classification, wd.APPROVED_SOURCE_UNAVAILABLE)
                self.assertEqual(fake.downloads, ["https://results.example/5150?sig=s"])
                code, _, _, _ = run_main(fake, "--notify", as_of=NOV)
                self.assertEqual((code, fake.writes), (0, []))

    def test_11c_failing_at_the_fetch_step_is_not_enough(self):
        fake = FakeGitHub()
        fake.run(515, "2026-11-15T10:20:00Z", conclusion="failure", failed_step=wd.FETCH_STEP)
        ev, v = check(fake, NOV)  # no log available: 404
        self.assertEqual(v.classification, wd.SCHEDULED_RUN_FAILED)
        self.assertIn("job log could not be read", v.reason)
        self.assertIn("needs investigation", v.reason)

    def test_11b_an_invalid_registry_approves_nothing(self):
        fake = FakeGitHub()
        fake.registry = json.loads(json.dumps(REAL_REGISTRY))
        fake.registry["periods"][0]["reason"] = "TODO"
        fake.run(515, "2026-11-15T10:20:00Z", conclusion="failure", failed_step=wd.FETCH_STEP)
        fake.logs[5150] = october_log()
        ev, v = check(fake, NOV)
        self.assertFalse(ev.approved_unavailable)
        self.assertEqual(fake.log_requests, [], "no log is read for an unapproved period")
        self.assertEqual(v.classification, wd.SCHEDULED_RUN_FAILED)
        self.assertIn("registry is not valid", v.reason)

    def test_12_future_missing_month_with_no_approved_exception(self):
        fake = FakeGitHub()
        fake.run(516, "2027-04-15T10:20:00Z", conclusion="failure", failed_step=wd.FETCH_STEP)
        fake.logs[5160] = actions_log("2027-03", *fetch_output("2027-03", {"2026-03"}))
        ev, v = check(fake, "2027-04-17T16:37:00Z")
        self.assertEqual(ev.period, "2027-03")
        self.assertEqual(v.classification, wd.SCHEDULED_RUN_FAILED)
        self.assertIn("no approved exception", v.reason)
        self.assertEqual(fake.log_requests, [])

    def test_stalled_and_in_progress_runs(self):
        fake = FakeGitHub()
        fake.run(517, "2026-12-17T10:20:00Z", status="in_progress")
        self.assertEqual(check(fake)[1].classification, wd.RUN_IN_PROGRESS)
        fake = FakeGitHub()
        fake.run(518, "2026-12-15T10:20:00Z", status="queued")
        self.assertEqual(check(fake)[1].classification, wd.SCHEDULED_RUN_STALLED)

    def test_scheduled_runs_from_another_cycle_are_ignored(self):
        fake = FakeGitHub()
        fake.run(519, "2026-11-15T10:20:00Z")
        self.assertEqual(check(fake)[1].classification, wd.SCHEDULED_RUN_MISSING)


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestSourceFailureEvidence(unittest.TestCase):
    """Only the documented limitation, shown in the job log, is expected.

    Every case fails at "Fetch CPI data (live only)" after every earlier
    step succeeded, in the approved period 2026-10. Only the first is
    explained.
    """

    def classify_with_log(self, log=None, status=None, download_error=None):
        fake = FakeGitHub()
        fake.run(560, "2026-11-15T10:20:00Z", conclusion="failure", failed_step=wd.FETCH_STEP)
        if log is not None:
            fake.logs[5600] = log
        if status is not None:
            fake.log_status[5600] = status
        fake.download_error = download_error
        ev, v = check(fake, NOV)
        return fake, ev, v

    def assert_alert(self, log=None, fragment="", **kwargs):
        fake, ev, v = self.classify_with_log(log, **kwargs)
        self.assertTrue(ev.approved_unavailable)
        self.assertEqual(v.classification, wd.SCHEDULED_RUN_FAILED, v.reason)
        self.assertTrue(v.alert)
        self.assertIn("needs investigation", v.reason)
        self.assertIn(fragment, v.reason)
        self.assertIn("job log:", wd.render(ev, v))
        code, _, _, _ = run_main(fake, "--notify", as_of=NOV)
        self.assertEqual((code, len(fake.issues)), (0, 1), "an Issue must be opened")
        return v

    def test_missing_october_2025_cpi_is_recognised(self):
        stdout, stderr, code = fetch_output("2026-10")
        self.assertIn("CPI has no observations for 2025-10 (12-month CPI base month).", stderr)
        _, _, v = self.classify_with_log(actions_log("2026-10", stdout, stderr, code))
        self.assertEqual(v.classification, wd.APPROVED_SOURCE_UNAVAILABLE)

    def test_bls_authentication_failure_alerts(self):
        exc = ValueError("BLS API error: The key provided by the User is invalid.")
        self.assert_alert(actions_log("2026-10", *fetch_output("2026-10", exc)),
                          "traceback")

    def test_network_failure_alerts(self):
        exc = ValueError("Failed to fetch CPI data from BLS API: HTTPSConnectionPool("
                         "host='api.bls.gov', port=443): Max retries exceeded "
                         "(Caused by NewConnectionError('Failed to establish a new connection'))")
        self.assert_alert(actions_log("2026-10", *fetch_output("2026-10", exc)), "traceback")

    def test_timeout_alerts(self):
        self.assert_alert(actions_log("2026-10", *fetch_output("2026-10", TimeoutError(
            "The read operation timed out"))), "traceback")

    def test_unexpected_exception_alerts(self):
        self.assert_alert(actions_log("2026-10", *fetch_output("2026-10", KeyError("series"))),
                          "traceback")

    def test_more_missing_data_than_documented_alerts(self):
        from tests.test_reference_period_staging import CPI_SERIES, U3_SERIES
        some_cpi = sorted(CPI_SERIES)[0]
        for drop, problem in (({"2026-10"}, "reference month"),
                              ({("2026-10", some_cpi)}, "CPI observation missing"),
                              ({("2026-10", U3_SERIES)}, "U-3 has no observation")):
            with self.subTest(problem=problem):
                stdout, stderr, code = fetch_output("2026-10", drop)
                self.assertIn(problem, stderr)
                self.assert_alert(actions_log("2026-10", stdout, stderr, code),
                                  "the acquisition error lists")

    def test_log_for_another_period_alerts(self):
        self.assert_alert(actions_log("2026-09", *fetch_output("2026-10")), "no single")

    def test_log_without_the_exit_or_validation_alerts(self):
        stdout, stderr, _ = fetch_output("2026-10")
        self.assert_alert(actions_log("2026-10", stdout, stderr, 0), "exit with code 1")
        cut = stdout.split("[3/3]")[0]
        self.assert_alert(actions_log("2026-10", cut, stderr, 1), "did not complete")

    def test_repeated_acquisition_error_alerts(self):
        stdout, stderr, code = fetch_output("2026-10")
        self.assert_alert(actions_log("2026-10", stdout, stderr + stderr, code), "exactly one")

    def test_unreadable_log_alerts(self):
        for status in (401, 403, 404, 410, 500):
            with self.subTest(status=status):
                self.assert_alert(status=status, fragment=f"HTTP {status}")
        self.assert_alert(october_log(), "download failed",
                          download_error="job log download failed: timed out")

    def test_registry_entry_must_name_the_missing_base_month(self):
        fake = FakeGitHub()
        fake.registry = json.loads(json.dumps(REAL_REGISTRY))
        entry = fake.registry["periods"][0]
        entry["detail"] = entry["detail"].replace("October 2025", "the base month")
        fake.run(560, "2026-11-15T10:20:00Z", conclusion="failure", failed_step=wd.FETCH_STEP)
        fake.logs[5600] = october_log()
        ev, v = check(fake, NOV)
        self.assertTrue(ev.approved_unavailable)
        self.assertEqual(v.classification, wd.SCHEDULED_RUN_FAILED)
        self.assertIn("does not name 2025-10", v.reason)

    def test_base_month(self):
        self.assertEqual(wd.base_month("2026-10"), "2025-10")
        self.assertEqual(wd.base_month("2027-01"), "2026-01")


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestApprovedExceptionReport(unittest.TestCase):
    """For an approved period the report names the exception and asks for no rerun."""

    SAMPLE = (
        "The scheduled October 2026 release preparation failed during Python setup. "
        "This infrastructure defect has since been repaired: run 602 on main "
        "(2026-11-23, https://github.com/dmianalysis/dmi/actions/runs/602) passed "
        "'Set up Python'. October 2026 cannot be published under DMI's methodology "
        "because the necessary October 2025 CPI comparison observations are "
        "unavailable, as documented in PR #40. No October release rerun is required. "
        "Record the incident as resolved after verifying the corrective changes, and "
        "confirm that the December 15 preparation of November 2026 data succeeds.")

    def november(self, later=None):
        fake = FakeGitHub()
        fake.run(601, "2026-11-15T17:14:00Z", conclusion="failure", failed_step="Set up Python")
        if later:
            later(fake)
        ev, v = check(fake, "2026-11-24T04:19:00Z")
        return ev, v, wd.render(ev, v)

    def test_matches_the_approved_wording_when_a_later_run_proves_the_repair(self):
        ev, v, body = self.november(lambda f: f.run(
            602, "2026-11-23T17:06:00Z", event="workflow_dispatch", conclusion="failure",
            failed_step="Compute DMI Baseline (live only)"))
        self.assertEqual(v.classification, wd.SCHEDULED_RUN_FAILED)
        self.assertEqual(wd.suggested_action(ev, v), self.SAMPLE)
        self.assertIn("**Approved data exception:** 2026-10 has no published DMI because the "
                      "required official CPI comparison data are unavailable (approved in "
                      "dmianalysis/dmi#40). No 2026-10 release is expected", body)
        for generic in ("prepare the release manually", "record that in registry",
                        "If the official data"):
            self.assertNotIn(generic, body)

    def test_repair_is_not_claimed_without_evidence(self):
        cases = {
            "no later run": None,
            "later run on another branch": lambda f: f.run(
                602, "2026-11-23T16:12:00Z", event="workflow_dispatch", data_source="fixture",
                branch="fix/python-runtime-modernization"),
            "later run failed at the same step": lambda f: f.run(
                602, "2026-11-20T09:00:00Z", event="workflow_dispatch", conclusion="failure",
                failed_step="Set up Python"),
        }
        for name, later in cases.items():
            with self.subTest(case=name):
                ev, v, body = self.november(later)
                action = wd.suggested_action(ev, v)
                self.assertNotIn("has since been repaired", action)
                self.assertIn("No later run on main has passed 'Set up Python' yet, so the "
                              "repair is not confirmed.", action)
                self.assertIn("No October release rerun is required.", action)
                self.assertIn("once a run on main passes that step", action)

    def test_an_earlier_run_is_not_evidence_of_repair(self):
        fake = FakeGitHub()
        fake.run(600, "2026-11-10T09:00:00Z", event="workflow_dispatch")
        fake.run(601, "2026-11-15T17:14:00Z", conclusion="failure", failed_step="Set up Python")
        ev, v = check(fake, "2026-11-24T04:19:00Z")
        self.assertNotIn("has since been repaired", wd.suggested_action(ev, v))

    def test_unexplained_fetch_failure_points_at_the_log(self):
        fake = FakeGitHub()
        fake.run(603, "2026-11-15T10:20:00Z", conclusion="failure", failed_step=wd.FETCH_STEP)
        fake.logs[6030] = actions_log("2026-10", *fetch_output("2026-10", TimeoutError("t")))
        ev, v = check(fake, NOV)
        action = wd.suggested_action(ev, v)
        self.assertIn("failed at step 'Fetch CPI data (live only)', and the job log does not "
                      "show the documented limitation (the step raised an exception", action)
        self.assertIn("Read the failed step's log to find the actual cause", action)
        self.assertIn("No October release rerun is required.", action)

    def test_missing_trigger_in_an_approved_period(self):
        ev, v = check(FakeGitHub(), NOV)
        action = wd.suggested_action(ev, v)
        self.assertIn("No scheduled run of monthly_dmi.yml started for the October 2026 "
                      "release.", action)
        self.assertIn("no October release rerun is required", action)
        self.assertIn("December 15 preparation of November 2026 data starts and succeeds", action)

    def test_unapproved_periods_keep_the_generic_action(self):
        fake = FakeGitHub()
        fake.run(604, "2026-12-15T17:14:00Z", conclusion="failure", failed_step="Set up Python")
        ev, v = check(fake)
        body = wd.render(ev, v)
        self.assertNotIn("Approved data exception", body)
        self.assertIn("prepare the release manually", body)
        self.assertIn("reference_period=2026-11", body)

    def test_invalid_registry_entry_is_not_presented_as_approved(self):
        fake = FakeGitHub()
        fake.registry = json.loads(json.dumps(REAL_REGISTRY))
        fake.registry["periods"][0]["reason"] = "TODO"
        fake.run(605, "2026-11-15T17:14:00Z", conclusion="failure", failed_step="Set up Python")
        ev, v = check(fake, NOV)
        body = wd.render(ev, v)
        self.assertNotIn("Approved data exception", body)
        self.assertNotIn("No October release rerun is required", body)

    def test_next_preparation_crosses_the_year(self):
        fake = FakeGitHub()
        fake.manifest_ids = ["2027-10"]
        fake.registry = json.loads(json.dumps(REAL_REGISTRY))
        entry = json.loads(json.dumps(REAL_REGISTRY["periods"][0]))
        entry.update(release_id="2027-11", detail=entry["detail"].replace(
            "October 2025", "November 2026"))
        fake.registry["periods"] = [entry]
        fake.run(606, "2027-12-15T10:20:00Z", conclusion="failure", failed_step="Set up Python")
        ev, v = check(fake, "2027-12-17T16:37:00Z")
        action = wd.suggested_action(ev, v)
        self.assertIn("The scheduled November 2027 release preparation", action)
        self.assertIn("November 2026 CPI comparison observations", action)
        self.assertIn("January 15 preparation of December 2027 data", action)

    def test_wording_does_not_change_the_issue_state(self):
        _, v, _ = self.november()
        self.assertEqual(v.fingerprint("2026-10"),
                         "2026-10:SCHEDULED_RUN_FAILED:run=601:failure")

    def test_labels(self):
        self.assertEqual(wd.period_label("2026-10"), "October 2026")
        self.assertEqual(wd._review_label("dmianalysis/dmi#40", "dmianalysis/dmi"), "PR #40")
        self.assertEqual(wd._review_label("other/repo#7", "dmianalysis/dmi"), "PR other/repo#7")


class TestLogTransport(unittest.TestCase):
    """The token goes to the API only, never to the redirected log host."""

    def test_redirects_are_not_followed(self):
        handler = wd._NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, "Found", {},
                                                   "https://results.example/x"))

    def test_api_transport_is_built_without_redirect_following(self):
        built = []
        real = wd.urllib.request.build_opener

        def capture(*handlers):
            built.append(handlers)
            return real(*handlers)
        with patch.object(wd.urllib.request, "build_opener", capture):
            wd.urllib_transport("token", "https://api.github.com")
        self.assertEqual(built, [(wd._NoRedirect,)])

    def test_download_sends_no_token(self):
        seen = []

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(req, timeout):
            seen.append(req)
            return Response(b"log text")
        with patch.object(wd.urllib.request, "urlopen", fake_urlopen):
            self.assertEqual(wd.urllib_download("https://results.example/1?sig=s"), "log text")
        self.assertEqual(len(seen), 1)
        self.assertNotIn("Authorization", {k.title() for k in seen[0].headers})

    def test_download_refuses_plain_http(self):
        def must_not_open(req, timeout):
            raise AssertionError("an http URL must be refused before any request")
        with patch.object(wd.urllib.request, "urlopen", must_not_open), \
                self.assertRaises(wd.WatchdogError):
            wd.urllib_download("http://results.example/1")

    def test_client_without_a_downloader_cannot_follow(self):
        fake = FakeGitHub()
        fake.logs[1] = "x"
        with self.assertRaises(wd.WatchdogError):
            wd.GitHubClient(REPO, fake).job_log(1)


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestIssues(unittest.TestCase):

    def failing(self):
        fake = FakeGitHub()
        fake.run(520, "2026-12-15T17:14:00Z", conclusion="failure", failed_step="Set up Python")
        return fake

    def test_alert_creates_one_assigned_issue(self):
        fake = self.failing()
        code, out, _, _ = run_main(fake, "--notify")
        self.assertEqual(code, 0)
        self.assertEqual(fake.writes, [("POST", f"/repos/{REPO}/issues")])
        body = fake.requests[-1][2]
        self.assertEqual(body["title"],
                         "[DMI Watchdog] 2026-11 — release preparation requires attention")
        self.assertTrue(body["body"].startswith("<!-- dmi-watchdog:2026-11 -->"))
        self.assertEqual(body["assignees"], ["tcwilliams79"])

    def test_13_repeated_daily_checks_produce_no_duplicate(self):
        fake = self.failing()
        for day in ("2026-12-17T16:37:00Z", "2026-12-18T16:37:00Z", "2026-12-19T16:37:00Z"):
            self.assertEqual(run_main(fake, "--notify", as_of=day)[0], 0)
        self.assertEqual(len(fake.issues), 1)
        self.assertEqual(len(fake.writes), 1)

    def test_a_meaningful_change_adds_exactly_one_update(self):
        fake = self.failing()
        run_main(fake, "--notify")
        fake.run(521, "2026-12-18T09:00:00Z", event="workflow_dispatch")
        fake.pr(68, "2026-11", "2026-12-18T09:30:00Z")
        for day in ("2026-12-18T16:37:00Z", "2026-12-19T16:37:00Z"):
            run_main(fake, "--notify", as_of=day)
        number = fake.issues[0]["number"]
        self.assertEqual(len(fake.comments[number]), 1)
        self.assertIn("no action needed now", fake.comments[number][0]["body"])
        self.assertEqual(fake.issues[0]["state"], "open", "never closed automatically")

    def test_14_closed_issue_is_not_duplicated(self):
        fake = self.failing()
        fake.issue(77, "2026-11", state="closed",
                   fingerprint="2026-11:SCHEDULED_RUN_MISSING")
        run_main(fake, "--notify")
        self.assertEqual(len(fake.issues), 1, "no second Issue for the same period")
        self.assertEqual(fake.writes, [("POST", f"/repos/{REPO}/issues/77/comments")])
        self.assertEqual(fake.issues[0]["state"], "closed", "never reopened automatically")
        run_main(fake, "--notify", as_of="2026-12-18T16:37:00Z")
        self.assertEqual(len(fake.writes), 1)

    def test_14b_closed_issue_gets_nothing_when_all_is_well(self):
        fake = FakeGitHub()
        healthy_december(fake)
        fake.issue(78, "2026-11", state="closed", fingerprint="2026-11:SCHEDULED_RUN_MISSING")
        run_main(fake, "--notify")
        self.assertEqual(fake.writes, [])

    def test_issues_for_other_periods_are_not_reused(self):
        fake = self.failing()
        fake.issue(79, "2026-10", state="open")
        run_main(fake, "--notify")
        self.assertEqual([i["number"] for i in fake.issues], [79, 901])


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestFailuresAreExplicit(unittest.TestCase):

    def test_15_authorization_failure_is_not_zero_runs(self):
        for prefix in ("/actions/workflows/7/runs", "/actions/runs/", "/pulls",
                       "/contents/data", "/issues"):
            with self.subTest(prefix=prefix):
                fake = FakeGitHub()
                fake.run(530, "2026-12-15T17:14:00Z", conclusion="failure",
                         failed_step="Set up Python")
                fake.fail[prefix] = (401, "Bad credentials")
                code, out, err, summary = run_main(fake, "--notify")
                self.assertEqual(code, 2)
                self.assertNotIn(wd.SCHEDULED_RUN_MISSING, out + err)
                self.assertIn("HTTP 401", err)
                self.assertIn("ERROR", summary)
                self.assertIn("not the same as finding nothing", summary)
                self.assertEqual(fake.writes, [])

    def test_missing_manifest_is_an_error_not_an_absent_release(self):
        fake = FakeGitHub()
        fake.fail["/contents/data/outputs/releases.json"] = (404, "Not Found")
        self.assertEqual(run_main(fake)[0], 2)

    def test_malformed_listing_is_an_error(self):
        fake = FakeGitHub()
        original = fake.__call__

        def broken(method, path, body):
            if "/runs?" in path:
                return 200, {"total_count": 0}
            return original(method, path, body)
        self.assertEqual(run_main(broken)[0], 2)

    def test_wrong_workflow_path_is_an_error(self):
        fake = FakeGitHub()
        original = fake.__call__

        def other(method, path, body):
            status, payload = original(method, path, body)
            if path.endswith("/actions/workflows/monthly_dmi.yml"):
                payload = {**payload, "path": ".github/workflows/other.yml"}
            return status, payload
        self.assertEqual(run_main(other)[0], 2)

    def test_missing_token_or_repo_fails(self):
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            env = {k: os.environ.pop(k) for k in ("GH_TOKEN", "GITHUB_TOKEN") if k in os.environ}
            try:
                self.assertEqual(wd.main(["--repo", REPO]), 2)
            finally:
                os.environ.update(env)
            self.assertEqual(wd.main(["--repo", "not a repo"], transport=FakeGitHub()), 2)


class TestDates(unittest.TestCase):

    def test_16_reference_period_from_the_check_date(self):
        cases = {
            "2026-11-17T16:37:00Z": "2026-10",
            "2026-12-17T16:37:00Z": "2026-11",
            "2027-01-17T16:37:00Z": "2026-12",
            "2027-01-01T00:00:00Z": "2026-12",
            "2026-12-31T23:59:59Z": "2026-11",
            # 19:30 on Dec 31 in New York is already January in UTC.
            "2026-12-31T19:30:00-05:00": "2026-12",
            "2027-02-28T16:37:00Z": "2027-01",
        }
        for when, period in cases.items():
            with self.subTest(when=when):
                self.assertEqual(wd.expected_period(utc(when)), period)

    def test_as_of_parsing(self):
        now = lambda: utc("2026-12-20T08:00:00Z")
        self.assertEqual(wd.parse_as_of(None, now), now())
        self.assertEqual(wd.parse_as_of("2026-12-17", now), utc("2026-12-17T23:59:59Z"))
        self.assertEqual(wd.parse_as_of("2026-12-17T16:37Z", now), utc("2026-12-17T16:37:00Z"))
        for bad in ("17/12/2026", "2026-12-17T16:37"):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                wd.parse_as_of(bad, now)

    @unittest.skipIf(yaml is None, "PyYAML not available")
    def test_january_cycle_crosses_the_year(self):
        fake = FakeGitHub()
        fake.manifest_ids.insert(0, "2026-11")
        fake.run(540, "2027-01-15T10:20:00Z")
        fake.pr(70, "2026-12", "2027-01-15T10:40:00Z")
        ev, v = check(fake, "2027-01-17T16:37:00Z")
        self.assertEqual((ev.period, v.classification), ("2026-12", wd.RELEASE_PR_PENDING_REVIEW))


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestDryRun(unittest.TestCase):

    def test_17_dry_run_makes_no_github_writes(self):
        fake = FakeGitHub()
        fake.run(550, "2026-12-15T17:14:00Z", conclusion="failure", failed_step="Set up Python")
        for argv in ((), ("--dry-run",), ("--dry-run", "--as-of", "2026-12-17")):
            with self.subTest(argv=argv):
                code, out, _, summary = run_main(fake, *argv)
                self.assertEqual(code, 0)
                self.assertEqual(fake.writes, [])
                for needed in ("dry run (no GitHub writes)", "Expected reference period:** 2026-11",
                               "Scheduled runs this cycle", "Release PRs for 2026-11",
                               "data/outputs/releases.json on main", "registry/unavailable_periods.json",
                               "Classification:** `SCHEDULED_RUN_FAILED`",
                               "Issue action:** create"):
                    self.assertIn(needed, out)
                self.assertEqual(out.strip(), summary.strip())

    def test_dry_run_client_refuses_writes_outright(self):
        gh = wd.GitHubClient(REPO, FakeGitHub(), allow_writes=False)
        with self.assertRaises(wd.WatchdogError):
            gh.post("/issues", {"title": "x"})

    def test_replayed_dates_cannot_notify(self):
        fake = FakeGitHub()
        code, _, err, _ = run_main(fake, "--notify", "--as-of", "2026-12-17")
        self.assertEqual((code, fake.writes), (2, []))
        self.assertIn("dry-run", err)


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestNoPublicationAuthority(unittest.TestCase):
    """18: no reruns, merges, deployment or repository writes."""

    def test_client_permits_only_issue_creation_and_comments(self):
        sent = []

        def accepts_anything(method, path, body):
            sent.append((method, path))
            return 201, {}
        gh = wd.GitHubClient(REPO, accepts_anything, allow_writes=True)
        gh.post("/issues", {})
        gh.post("/issues/5/comments", {})
        self.assertEqual(len(sent), 2)
        for suffix in ("/actions/runs/1/rerun", "/actions/runs/1/rerun-failed-jobs",
                       "/actions/workflows/7/dispatches", "/pulls/1/merge",
                       "/pulls/1/reviews", "/merges", "/deployments", "/dispatches",
                       "/git/refs", "/issues/1/labels", "/contents/data/outputs/releases.json"):
            with self.subTest(suffix=suffix), self.assertRaises(wd.WatchdogError):
                gh.post(suffix, {})
        self.assertEqual(len(sent), 2, "a refused write must never be sent")
        self.assertFalse(hasattr(gh, "put") or hasattr(gh, "patch") or hasattr(gh, "delete"))

    def test_module_sends_only_get_and_post(self):
        methods = set(re.findall(r'_send\("([A-Z]+)"', MODULE.read_text()))
        self.assertEqual(methods, {"GET", "POST"})
        self.assertEqual(re.findall(r"\b(PUT|PATCH|DELETE)\b", MODULE.read_text()), [])

    def test_module_writes_no_local_files_except_the_run_summary(self):
        tree = ast.parse(MODULE.read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        names = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
                 for n in calls}
        self.assertFalse(names & {"write_text", "write_bytes", "dump", "mkdir", "unlink",
                                  "rmtree", "run", "Popen", "system"})
        opens = [n for n in calls if getattr(n.func, "id", "") == "open"]
        self.assertEqual(len(opens), 1)
        self.assertIn("GITHUB_STEP_SUMMARY", ast.get_source_segment(MODULE.read_text(),
                                                                   _enclosing(tree, opens[0])))

    def test_module_is_independent_of_the_pipeline(self):
        imported = set()
        for node in ast.walk(ast.parse(MODULE.read_text())):
            if isinstance(node, ast.ImportFrom):
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
        repo_modules = {m for m in imported if m and m.split(".")[0] in ("scripts", "dmi_pipeline",
                                                                       "dmi_calculator")}
        self.assertEqual(repo_modules, {"scripts.unavailable_periods"})

    def test_workflow_permissions_and_triggers(self):
        doc = yaml.safe_load(WATCHDOG_WORKFLOW.read_text())
        self.assertEqual(doc["permissions"], {"contents": "read", "actions": "read",
                                              "pull-requests": "read", "issues": "write"})
        on = doc.get("on", doc.get(True))
        self.assertEqual(set(on), {"schedule", "workflow_dispatch"})
        self.assertEqual(on["schedule"], [{"cron": "37 16 17-28 * *"}])
        self.assertIs(on["workflow_dispatch"]["inputs"]["notify"]["default"], False)
        for job in doc["jobs"].values():
            self.assertEqual(job["runs-on"], "ubuntu-latest")
            self.assertNotIn("permissions", job)

    def test_workflow_holds_no_secrets_and_cannot_deploy(self):
        text = WATCHDOG_WORKFLOW.read_text()
        self.assertNotIn("secrets.", text)
        doc = yaml.safe_load(text)
        steps = [s for job in doc["jobs"].values() for s in job["steps"]]
        code = "\n".join(line for s in steps for line in str(s.get("run", "")).splitlines()
                         if not line.strip().startswith("#"))
        for forbidden in ("ssh", "rsync", "scp", "sftp", "deploy", "gh workflow", "gh run",
                          "gh pr", "gh api", "git push", "git commit", "curl", "rerun",
                          "finalize_release", "compute_dmi", "test_bls_api", "prepare_deployment"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, code)
        uses = {str(s.get("uses", "")).split("@")[0] for s in steps if s.get("uses")}
        self.assertEqual(uses, {"actions/checkout"})
        checkout = next(s for s in steps if str(s.get("uses", "")).startswith("actions/checkout"))
        self.assertIs(checkout["with"]["persist-credentials"], False)

    def test_watchdog_is_not_a_deployment_workflow(self):
        from tests import test_monthly_workflow_safety as safety
        self.assertIn(WATCHDOG_WORKFLOW, safety.ALL_WORKFLOWS)
        self.assertNotIn(WATCHDOG_WORKFLOW, safety.DEPLOY_WORKFLOWS)
        deploy = (WORKFLOWS / "deploy_production.yml").read_text()
        self.assertNotIn("monthly_release_watchdog", deploy)
        self.assertNotIn("workflow_run", WATCHDOG_WORKFLOW.read_text())

    def test_reminder_workflow_keeps_its_own_job(self):
        reminder = (WORKFLOWS / "release_gate_reminder.yml").read_text()
        self.assertNotIn("watchdog", reminder)
        self.assertNotIn("gh pr comment", WATCHDOG_WORKFLOW.read_text())


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestWorkflowWiring(unittest.TestCase):
    """The workflow's shell picks the mode; run it against a stub python."""

    def run_step(self, event, as_of="", notify=""):
        doc = yaml.safe_load(WATCHDOG_WORKFLOW.read_text())
        step = next(s for s in doc["jobs"]["watch"]["steps"]
                    if s["name"] == "Check this month's release preparation")
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "python3"
            stub.write_text('#!/bin/sh\necho "$@"\n')
            stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
            env = {"PATH": f"{tmp}:{os.environ['PATH']}", "EVENT_NAME": event,
                   "INPUT_AS_OF": as_of, "INPUT_NOTIFY": notify}
            out = subprocess.run(["bash", "-e", "-c", step["run"]], env=env,
                                 capture_output=True, text=True, check=True)
        return out.stdout.split()

    def test_scheduled_runs_notify(self):
        self.assertEqual(self.run_step("schedule"),
                         ["-m", "scripts.monthly_release_watchdog", "--notify"])

    def test_manual_runs_default_to_dry_run(self):
        self.assertEqual(self.run_step("workflow_dispatch", notify="false")[-1], "--dry-run")
        self.assertEqual(self.run_step("workflow_dispatch")[-1], "--dry-run")

    def test_manual_notify_must_be_ticked(self):
        self.assertEqual(self.run_step("workflow_dispatch", notify="true")[-1], "--notify")

    def test_replayed_date_is_always_a_dry_run(self):
        args = self.run_step("workflow_dispatch", as_of="2026-12-17", notify="true")
        self.assertEqual(args[-3:], ["--as-of", "2026-12-17", "--dry-run"])
        self.assertNotIn("--notify", args)

    def test_classification_relies_on_real_step_names(self):
        names = monthly_step_names()
        for step in (wd.FETCH_STEP, wd.CREATE_PR_STEP, "Set up Python"):
            self.assertIn(step, names)
        monthly = yaml.safe_load((WORKFLOWS / "monthly_dmi.yml").read_text())
        on = monthly.get("on", monthly.get(True))
        self.assertEqual(on["schedule"], [{"cron": "17 10 15 * *"}],
                         "the watchdog's grace period assumes the 15th at 10:17 UTC")
        create = next(s for s in monthly["jobs"]["prepare-dmi"]["steps"]
                      if s["name"] == wd.CREATE_PR_STEP)["with"]
        self.assertEqual(create["title"],
                         "DMI Release: ${{ steps.period.outputs.period }} (not deployed)")
        self.assertEqual(create["branch"], "release/${{ steps.period.outputs.period }}")
        self.assertEqual(set(create["labels"].split()) & wd.RELEASE_LABELS, wd.RELEASE_LABELS)


def _enclosing(tree, target):
    """The innermost function definition containing ``target``."""
    best = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and any(n is target for n in ast.walk(node)):
            if best is None or node.lineno > best.lineno:
                best = node
    return best


if __name__ == "__main__":
    unittest.main()
